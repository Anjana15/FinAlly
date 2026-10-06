"""Through the real app (real app.db, app.services, simulator) with LLM_MOCK=true. No network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    from app.main import create_app

    with TestClient(create_app(static_dir=tmp_path / "no-static")) as c:
        yield c


def test_buy_via_chat_executes(client):
    cash_before = client.get("/api/portfolio").json()["cash"]

    r = client.post("/api/chat", json={"message": "buy 1 AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "Placing a buy order for 1 AAPL."
    trade = body["actions"]["trades"][0]
    assert trade["status"] == "executed" and trade["ticker"] == "AAPL" and trade["quantity"] == 1

    portfolio = client.get("/api/portfolio").json()
    assert any(p["ticker"] == "AAPL" and p["quantity"] == 1 for p in portfolio["positions"])
    assert portfolio["cash"] == pytest.approx(cash_before - trade["price"], abs=0.01)

    history = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in history[-2:]] == ["user", "assistant"]
    assert history[-1]["actions"]["trades"][0]["status"] == "executed"


def test_failed_sell_and_watchlist_via_chat(client):
    body = client.post("/api/chat", json={"message": "sell 5 NVDA"}).json()
    assert body["actions"]["trades"][0]["status"] == "failed"
    assert body["actions"]["trades"][0]["error"] == "insufficient_shares"

    body = client.post("/api/chat", json={"message": "add PYPL"}).json()
    assert body["actions"]["watchlist_changes"] == [{"ticker": "PYPL", "action": "add", "status": "added"}]
    tickers = [t["ticker"] for t in client.get("/api/watchlist").json()["tickers"]]
    assert "PYPL" in tickers


def test_empty_message(client):
    r = client.post("/api/chat", json={"message": " "})
    assert r.status_code == 400 and r.json()["error"] == "empty_message"
