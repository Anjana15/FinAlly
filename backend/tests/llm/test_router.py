from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.router import router


@pytest.fixture
def http(monkeypatch, fake_db, fake_services, fake_app):
    app = FastAPI()
    app.include_router(router)
    app.state.prices = fake_app.state.prices
    monkeypatch.setenv("LLM_MOCK", "true")
    return TestClient(app)


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   "}, {}, {"message": 3}, []])
def test_empty_message_400(http, body):
    r = http.post("/api/chat", json=body)
    assert r.status_code == 400
    assert r.json()["error"] == "empty_message" and r.json()["detail"]


def test_non_json_400(http):
    r = http.post("/api/chat", content=b"nope", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "empty_message"


def test_chat_ok(http, fake_services):
    r = http.post("/api/chat", json={"message": "  buy 2 AAPL "})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "assistant" and body["content"] == "Placing a buy order for 2 AAPL."
    assert set(body) == {"id", "role", "content", "created_at", "actions"}
    assert fake_services.trade_calls == [("AAPL", "buy", 2.0)]
