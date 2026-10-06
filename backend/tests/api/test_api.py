from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db


def assert_error(resp, status: int, code: str):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["error"] == code
    assert isinstance(body["detail"], str) and body["detail"]


# ---- health ----

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["market"]["source"] == "simulator"
    assert set(body["market"]) == {"source", "state", "message"}


# ---- watchlist ----

def test_get_watchlist_seeded_with_quotes(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    rows = r.json()["tickers"]
    assert [x["ticker"] for x in rows] == list(db.DEFAULT_WATCHLIST)
    q = rows[0]["quote"]
    assert set(q) == {"ticker", "price", "previous_price", "reference_price", "change",
                      "change_percent", "direction", "timestamp"}


def test_add_watchlist_then_duplicate(client):
    r = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "PYPL" and body["status"] == "added"
    assert body["quote"] is not None and body["quote"]["ticker"] == "PYPL"
    r = client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert r.status_code == 200 and r.json()["status"] == "exists"
    assert [x["ticker"] for x in client.get("/api/watchlist").json()["tickers"]][-1] == "PYPL"


@pytest.mark.parametrize("payload", [{"ticker": "bad ticker"}, {"ticker": "123"}, {"ticker": 5}, {}])
def test_add_watchlist_invalid(client, payload):
    assert_error(client.post("/api/watchlist", json=payload), 400, "invalid_ticker")


def test_remove_watchlist(client):
    r = client.delete("/api/watchlist/aapl")
    assert r.status_code == 200
    assert r.json() == {"ticker": "AAPL", "status": "removed"}
    assert "AAPL" not in [x["ticker"] for x in client.get("/api/watchlist").json()["tickers"]]
    assert "AAPL" not in client.app.state.market.tickers()


def test_remove_watchlist_not_found(client):
    assert_error(client.delete("/api/watchlist/PYPL"), 404, "not_found")


def test_remove_watchlist_invalid(client):
    assert_error(client.delete("/api/watchlist/12345"), 400, "invalid_ticker")


def test_remove_held_ticker_keeps_tracking(client):
    assert client.post("/api/portfolio/trade", json={"ticker": "TSLA", "side": "buy", "quantity": 1}).status_code == 200
    assert client.delete("/api/watchlist/TSLA").status_code == 200
    assert "TSLA" in client.app.state.market.tickers()
    pos = client.get("/api/portfolio").json()["positions"]
    assert pos[0]["ticker"] == "TSLA" and pos[0]["price"] is not None


# ---- trades ----

def test_buy_then_sell(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "aapl", "side": "buy", "quantity": 1.5})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["status"] == "executed" and t["ticker"] == "AAPL" and t["side"] == "buy"
    assert t["quantity"] == 1.5
    assert t["cash_balance"] == pytest.approx(10000 - round(1.5 * t["price"], 2))
    snaps = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snaps) >= 2  # startup + post-trade

    p = client.get("/api/portfolio").json()
    assert p["cash"] == t["cash_balance"]
    assert p["positions"][0]["ticker"] == "AAPL" and p["positions"][0]["quantity"] == 1.5

    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "sell", "quantity": 1.5})
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert client.get("/api/portfolio").json()["positions"] == []


def test_buy_adds_ticker_to_watchlist(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "PYPL", "side": "buy", "quantity": 1})
    assert r.status_code == 200, r.text
    assert "PYPL" in [x["ticker"] for x in client.get("/api/watchlist").json()["tickers"]]


def test_insufficient_cash(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 100000})
    assert_error(r, 400, "insufficient_cash")
    assert r.json()["status"] == "failed"
    assert client.get("/api/portfolio").json()["cash"] == 10000.0


def test_insufficient_shares(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "sell", "quantity": 1})
    assert_error(r, 400, "insufficient_shares")


@pytest.mark.parametrize("payload,code", [
    ({"ticker": "AAPL", "side": "hold", "quantity": 1}, "invalid_side"),
    ({"ticker": "AAPL", "side": 3, "quantity": 1}, "invalid_side"),
    ({"ticker": "AAPL", "quantity": 1}, "invalid_side"),
    ({"ticker": "AAPL", "side": "buy", "quantity": 0}, "invalid_quantity"),
    ({"ticker": "AAPL", "side": "buy", "quantity": -2}, "invalid_quantity"),
    ({"ticker": "AAPL", "side": "buy", "quantity": "lots"}, "invalid_quantity"),
    ({"ticker": "AAPL", "side": "buy"}, "invalid_quantity"),
    ({"ticker": "12", "side": "buy", "quantity": 1}, "invalid_ticker"),
    ({"side": "buy", "quantity": 1}, "invalid_ticker"),
])
def test_trade_validation_errors(client, payload, code):
    assert_error(client.post("/api/portfolio/trade", json=payload), 400, code)


def test_trade_malformed_json(client):
    r = client.post("/api/portfolio/trade", content=b"{not json", headers={"content-type": "application/json"})
    assert_error(r, 400, "invalid_request")


# ---- portfolio ----

def test_portfolio_valuation_math(client):
    client.post("/api/portfolio/trade", json={"ticker": "MSFT", "side": "buy", "quantity": 2})
    client.post("/api/portfolio/trade", json={"ticker": "NVDA", "side": "buy", "quantity": 3})
    p = client.get("/api/portfolio").json()
    assert p["valuation_complete"] is True
    for row in p["positions"]:
        assert row["market_value"] == pytest.approx(row["quantity"] * row["price"], abs=0.01)
        assert row["unrealized_pnl"] == pytest.approx(row["quantity"] * (row["price"] - row["avg_cost"]), abs=0.01)
        assert row["pnl_percent"] == pytest.approx((row["price"] - row["avg_cost"]) / row["avg_cost"] * 100, abs=0.01)
    total = p["cash"] + sum(r["quantity"] * r["price"] for r in p["positions"])
    assert p["total_value"] == pytest.approx(total, abs=0.02)


def test_portfolio_initial(client):
    p = client.get("/api/portfolio").json()
    assert p == {"cash": 10000.0, "total_value": 10000.0, "valuation_complete": True, "positions": []}


def test_history(client):
    snaps = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snaps) >= 1  # the snapshot loop records at startup
    assert snaps[0]["total_value"] == 10000.0 and snaps[0]["recorded_at"].endswith("Z")
    for _ in range(3):
        db.record_snapshot(db.get_conn(), 10001.0)
    assert len(client.get("/api/portfolio/history?limit=2").json()["snapshots"]) == 2
    assert client.get("/api/portfolio/history?limit=0").status_code == 200


# ---- chat history (POST /api/chat is llm-engineer's) ----

def test_chat_history(client):
    assert client.get("/api/chat/history").json() == {"messages": []}
    r = client.post("/api/chat", json={"message": "buy 1 AAPL"})
    assert r.status_code == 200, r.text
    msgs = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"]["trades"][0]["status"] == "executed"
    assert len(client.get("/api/chat/history?limit=1").json()["messages"]) == 1


# ---- static mount ----

def test_static_mount_does_not_shadow_api(env):
    from app.main import create_app

    static = env / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>FinAlly</html>")
    (static / "api").mkdir()  # even a same-named dir must not win over the routers
    with TestClient(create_app(static_dir=static)) as c:
        assert "FinAlly" in c.get("/").text
        assert c.get("/api/health").json()["status"] == "ok"
        assert "tickers" in c.get("/api/watchlist").json()


def test_no_static_dir_serves_api_only(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
