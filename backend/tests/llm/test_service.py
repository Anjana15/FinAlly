from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm import client
from app.llm.service import FRIENDLY_ERRORS, handle_chat


def fake_completion(content: str | None = None, exc: Exception | None = None, seen: list | None = None):
    def _completion(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        if exc is not None:
            raise exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _completion


async def test_mock_buy_executes_and_stores(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "TRUE")
    out = await handle_chat(fake_app, "buy 1 AAPL")
    assert out["role"] == "assistant"
    assert out["content"] == "Placing a buy order for 1 AAPL."
    assert fake_services.trade_calls == [("AAPL", "buy", 1.0)]
    assert out["actions"]["error"] is None
    assert out["actions"]["trades"][0]["status"] == "executed"
    assert out["actions"]["watchlist_changes"] == []
    # user stored with actions None, assistant stored with actions
    assert [m["role"] for m in fake_db.messages] == ["user", "assistant"]
    assert fake_db.messages[0]["actions"] is None
    assert fake_db.messages[1]["actions"] == out["actions"]
    assert fake_db.messages[1]["id"] == out["id"]


async def test_failed_trade_reported(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")
    fake_services.fail_tickers.add("TSLA")
    out = await handle_chat(fake_app, "buy 1000 TSLA")
    t = out["actions"]["trades"][0]
    assert t["status"] == "failed" and t["error"] == "insufficient_cash"
    assert out["actions"]["error"] is None


async def test_execute_trade_raising_is_contained(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")

    async def boom(*a, **k):
        raise RuntimeError("kaboom")

    fake_services.trading.execute_trade = boom
    out = await handle_chat(fake_app, "buy 1 AAPL")
    assert out["actions"]["trades"][0]["status"] == "failed"
    assert out["actions"]["trades"][0]["error"] == "internal_error"


async def test_watchlist_changes(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")
    out = await handle_chat(fake_app, "add pypl")
    assert fake_services.watch_calls == [("add", "PYPL")]
    assert out["actions"]["watchlist_changes"] == [{"ticker": "PYPL", "action": "add", "status": "added"}]
    out = await handle_chat(fake_app, "remove NFLX")
    assert out["actions"]["watchlist_changes"] == [{"ticker": "NFLX", "action": "remove", "status": "not_found"}]


async def test_mock_fallback_no_actions(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")
    out = await handle_chat(fake_app, "hello")
    assert out["content"].startswith("Mock response:")
    assert out["actions"] == {"trades": [], "watchlist_changes": [], "error": None}
    assert fake_services.trade_calls == []


async def test_real_llm_actions_collected(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    seen: list = []
    content = ('{"message":"Placing orders.","trades":[{"ticker":"AAPL","side":"buy","quantity":2},'
               '{"ticker":"TSLA","side":"sell","quantity":1}],"watchlist_changes":[{"ticker":"PYPL","action":"add"}]}')
    monkeypatch.setattr(client, "_completion", fake_completion(content, seen=seen))
    fake_services.fail_tickers.add("TSLA")
    out = await handle_chat(fake_app, "do it")
    assert out["content"] == "Placing orders."
    assert [t["status"] for t in out["actions"]["trades"]] == ["executed", "failed"]
    assert out["actions"]["watchlist_changes"][0]["status"] == "added"
    kw = seen[0]
    assert kw["model"] == client.MODEL
    assert kw["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert kw["reasoning_effort"] == "low"
    assert kw["response_format"].__name__ == "LLMResponse"
    msgs = kw["messages"]
    assert msgs[0]["role"] == "system" and "FinAlly" in msgs[0]["content"]
    assert "Cash: $10,000.00" in msgs[0]["content"]
    assert "AAPL: $190.00" in msgs[0]["content"] and "TSLA: no price yet" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "do it"}


async def test_history_included_with_action_summary(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")
    fake_services.fail_tickers.add("TSLA")
    await handle_chat(fake_app, "buy 1000 TSLA")
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen: list = []
    monkeypatch.setattr(client, "_completion",
                        fake_completion('{"message":"ok","trades":[],"watchlist_changes":[]}', seen=seen))
    await handle_chat(fake_app, "what happened?")
    msgs = seen[0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "buy 1000 TSLA"
    assert "[Actions:" in msgs[2]["content"] and "FAILED (insufficient_cash" in msgs[2]["content"]


async def test_history_limited_to_20(monkeypatch, fake_db, fake_services, fake_app):
    for i in range(30):
        fake_db.add_message(None, "user" if i % 2 == 0 else "assistant", f"m{i}", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen: list = []
    monkeypatch.setattr(client, "_completion",
                        fake_completion('{"message":"ok","trades":[],"watchlist_changes":[]}', seen=seen))
    await handle_chat(fake_app, "now")
    msgs = seen[0]["messages"]
    assert len(msgs) == 1 + 20 + 1
    assert msgs[1]["content"] == "m10"


@pytest.mark.parametrize("completion, code", [
    (fake_completion(exc=RuntimeError("503 from provider")), "llm_unavailable"),
    (fake_completion("this is not json"), "llm_bad_response"),
    (fake_completion('{"message":"x"}'), "llm_bad_response"),
    (fake_completion(None), "llm_bad_response"),
])
async def test_llm_failures(monkeypatch, fake_db, fake_services, fake_app, completion, code):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(client, "_completion", completion)
    out = await handle_chat(fake_app, "buy 1 AAPL")
    assert out["actions"] == {"trades": [], "watchlist_changes": [], "error": code}
    assert out["content"] == FRIENDLY_ERRORS[code]
    assert fake_services.trade_calls == []
    assert fake_db.messages[-1]["actions"]["error"] == code


async def test_missing_key_not_configured(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    out = await handle_chat(fake_app, "buy 1 AAPL")
    assert out["actions"]["error"] == "llm_not_configured"
    assert "OPENROUTER_API_KEY" in out["content"]


async def test_context_failure_still_answers(monkeypatch, fake_db, fake_services, fake_app):
    monkeypatch.setenv("LLM_MOCK", "true")

    def broken(app, user_id="default"):
        raise RuntimeError("db gone")

    fake_services.portfolio_mod.portfolio_view = broken
    out = await handle_chat(fake_app, "buy 1 AAPL")
    assert out["actions"]["trades"][0]["status"] == "executed"
