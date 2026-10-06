"""POST /api/chat: context -> LLM (or mock) -> execute actions via app.services -> store -> return."""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from . import client, prompt
from .mock import mock_response
from .schema import LLMResponse

log = logging.getLogger(__name__)

FRIENDLY_ERRORS = {
    "llm_not_configured": (
        "Chat isn't configured yet: set OPENROUTER_API_KEY (or LLM_MOCK=true) and restart. "
        "No actions were taken."
    ),
    "llm_unavailable": (
        "Sorry, I couldn't reach the AI service just now. Please try again in a moment. "
        "No actions were taken."
    ),
    "llm_bad_response": (
        "Sorry, the AI service sent back a response I couldn't understand. Please try again. "
        "No actions were taken."
    ),
}


def _mod(name: str):
    # Resolved at call time (via sys.modules) so tests can substitute fakes.
    return importlib.import_module(name)


def mock_enabled() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


def _build_context(app, conn, user_id: str) -> str:
    db = _mod("app.db")
    portfolio = _mod("app.services.portfolio").portfolio_view(app, user_id=user_id)
    cache = app.state.prices
    watchlist = []
    for ticker in db.get_watchlist(conn, user_id=user_id):
        q = cache.get(ticker)
        watchlist.append((ticker, q.to_dict() if q is not None else None))
    return prompt.format_portfolio_context(portfolio, watchlist)


async def _get_llm_response(messages: list[dict], user_message: str) -> LLMResponse:
    if mock_enabled():
        return mock_response(user_message)
    return await client.call_llm(messages)


async def _execute_actions(app, reply: LLMResponse, user_id: str) -> dict[str, Any]:
    trading = _mod("app.services.trading")
    watchlist = _mod("app.services.watchlist")
    trades: list[dict] = []
    for t in reply.trades:
        try:
            result = await trading.execute_trade(app, t.ticker, t.side, t.quantity, user_id=user_id)
        except Exception as exc:  # execute_trade shouldn't raise; never let one bad trade kill the reply
            log.exception("execute_trade raised for %s", t)
            result = {"status": "failed", "ticker": t.ticker, "side": t.side, "quantity": t.quantity,
                      "error": "internal_error", "detail": str(exc)}
        trades.append(result)

    changes: list[dict] = []
    for w in reply.watchlist_changes:
        fn = watchlist.add_ticker if w.action == "add" else watchlist.remove_ticker
        try:
            result = await fn(app, w.ticker, user_id=user_id)
        except Exception as exc:
            log.exception("watchlist %s raised for %s", w.action, w.ticker)
            result = {"status": "failed", "ticker": w.ticker, "error": "internal_error", "detail": str(exc)}
        change = {"ticker": result.get("ticker", w.ticker), "action": w.action, "status": result["status"]}
        for key in ("error", "detail"):
            if key in result:
                change[key] = result[key]
        changes.append(change)

    return {"trades": trades, "watchlist_changes": changes, "error": None}


async def handle_chat(app, user_message: str, user_id: str = "default") -> dict:
    """Returns the stored assistant ChatMessage (TEAM_CONTRACT §3). LLM failures never raise."""
    db = _mod("app.db")
    conn = db.get_conn()

    history = db.get_recent_messages(conn, user_id=user_id, limit=prompt.HISTORY_LIMIT)
    db.add_message(conn, "user", user_message, None, user_id=user_id)

    try:
        context = _build_context(app, conn, user_id)
    except Exception:
        log.exception("could not build portfolio context")
        context = "## Current portfolio\n(unavailable right now)"
    messages = prompt.build_messages(context, history, user_message)

    try:
        reply = await _get_llm_response(messages, user_message)
    except client.LLMError as exc:
        content = FRIENDLY_ERRORS[exc.code]
        actions = {"trades": [], "watchlist_changes": [], "error": exc.code}
    except Exception:  # belt and braces: the chat endpoint must not 500 on LLM trouble
        log.exception("unexpected LLM failure")
        content = FRIENDLY_ERRORS["llm_unavailable"]
        actions = {"trades": [], "watchlist_changes": [], "error": "llm_unavailable"}
    else:
        actions = await _execute_actions(app, reply, user_id)
        content = reply.message

    return db.add_message(conn, "assistant", content, actions, user_id=user_id)
