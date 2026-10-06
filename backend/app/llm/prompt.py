"""System prompt, live portfolio context and chat history -> the LLM `messages` list."""

from __future__ import annotations

from typing import Any

HISTORY_LIMIT = 20

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant inside a simulated trading workstation (fake money, live prices).

What you do:
- Analyze the user's portfolio: composition, risk concentration, and unrealized P&L.
- Suggest trades with brief, data-driven reasoning.
- Execute trades when the user asks for one or agrees to your suggestion. Use market orders only; fractional quantities are allowed.
- Manage the watchlist proactively: add tickers the user is discussing, remove ones they no longer want.
- Be concise. Use the numbers in the portfolio context below; never invent prices or holdings.

How actions work:
- Put trades in `trades` and watchlist edits in `watchlist_changes`. They are executed automatically AFTER you reply, and they can still fail (e.g. insufficient cash or shares). So phrase actions as intent ("Placing a buy order for 5 AAPL."), never as completed ("Bought 5 AAPL.").
- Only include a trade when the user asked for it or agreed to it. Otherwise leave `trades` empty.
- A buy needs enough cash (quantity x current price); a sell needs enough shares. Check the context first and say so if an order cannot work.
- Earlier assistant turns show what actually executed in [Actions: ...]; trust those results over what was said.

Always respond with valid JSON matching the schema: {"message": str, "trades": [{"ticker": str, "side": "buy"|"sell", "quantity": number}], "watchlist_changes": [{"ticker": str, "action": "add"|"remove"}]}. All three fields are required; use empty arrays when there is nothing to do.
"""


def _money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _num(v: float) -> str:
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def format_portfolio_context(portfolio: dict, watchlist: list[tuple[str, dict | None]]) -> str:
    """`portfolio` is the GET /api/portfolio body; `watchlist` is [(ticker, Quote dict | None)]."""
    lines = ["## Current portfolio (live)"]
    lines.append(f"Cash: {_money(portfolio.get('cash'))}")
    total = portfolio.get("total_value")
    lines.append(
        f"Total value: {_money(total)}"
        + ("" if portfolio.get("valuation_complete", True) else " (incomplete: some positions unpriced)")
    )
    positions = portfolio.get("positions") or []
    if positions:
        lines.append("Positions:")
        for p in positions:
            pnl = p.get("unrealized_pnl")
            pct = p.get("pnl_percent")
            weight = ""
            if total and p.get("market_value") is not None:
                weight = f", weight {p['market_value'] / total * 100:.1f}%"
            pnl_text = "n/a" if pnl is None else f"{_money(pnl)} ({pct:+.2f}%)"
            lines.append(
                f"- {p['ticker']}: {_num(p['quantity'])} sh @ avg {_money(p['avg_cost'])}, "
                f"price {_money(p.get('price'))}, value {_money(p.get('market_value'))}, "
                f"P&L {pnl_text}{weight}"
            )
    else:
        lines.append("Positions: none")

    lines.append("")
    lines.append("## Watchlist (live quotes)")
    if not watchlist:
        lines.append("(empty)")
    for ticker, q in watchlist:
        if q is None:
            lines.append(f"- {ticker}: no price yet")
        else:
            lines.append(
                f"- {ticker}: {_money(q['price'])} ({q['change_percent']:+.2f}% since reference)"
            )
    return "\n".join(lines)


def summarize_actions(actions: dict | None) -> str:
    """One line describing what actually happened, appended to assistant history turns."""
    if not actions:
        return ""
    parts: list[str] = []
    if actions.get("error"):
        parts.append(f"LLM error {actions['error']}, nothing executed")
    for t in actions.get("trades") or []:
        desc = f"{t.get('side')} {_num(float(t.get('quantity') or 0))} {t.get('ticker')}"
        if t.get("status") == "executed":
            parts.append(f"{desc} executed @ {_money(t.get('price'))}")
        else:
            parts.append(f"{desc} FAILED ({t.get('error')}: {t.get('detail')})")
    for w in actions.get("watchlist_changes") or []:
        status = w.get("status")
        text = f"watchlist {w.get('action')} {w.get('ticker')}: {status}"
        if status == "failed":
            text += f" ({w.get('error')})"
        parts.append(text)
    return f"[Actions: {'; '.join(parts)}]" if parts else ""


def build_messages(
    context: str, history: list[dict[str, Any]], user_message: str
) -> list[dict[str, str]]:
    """System prompt + context, the last HISTORY_LIMIT turns (oldest first), then the new user message."""
    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n{context}"}]
    for m in history[-HISTORY_LIMIT:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or ""
        if role == "assistant":
            summary = summarize_actions(m.get("actions"))
            if summary:
                content = f"{content}\n{summary}"
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
