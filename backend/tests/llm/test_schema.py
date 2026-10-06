from __future__ import annotations

import pytest

from app.llm.client import LLMBadResponse, parse_response
from app.llm.schema import LLMResponse

GOOD = ('{"message":"ok","trades":[{"ticker":"AAPL","side":"buy","quantity":1.5}],'
        '"watchlist_changes":[{"ticker":"PYPL","action":"add"}]}')


def test_good_json():
    r = parse_response(GOOD)
    assert r.message == "ok"
    assert r.trades[0].quantity == 1.5
    assert r.watchlist_changes[0].action == "add"


def test_empty_arrays_ok():
    r = parse_response('{"message":"hi","trades":[],"watchlist_changes":[]}')
    assert r.trades == [] and r.watchlist_changes == []


@pytest.mark.parametrize("bad", [
    "",
    None,
    "not json",
    '{"message":"hi"}',                                   # arrays are required
    '{"message":"hi","trades":[],"watchlist_changes":[],"x":1}',
    '{"message":"hi","trades":[{"ticker":"AAPL","side":"hold","quantity":1}],"watchlist_changes":[]}',
    '{"message":"hi","trades":[],"watchlist_changes":[{"ticker":"AAPL","action":"toggle"}]}',
    '{"message":"hi","trades":[{"ticker":"AAPL","side":"buy"}],"watchlist_changes":[]}',
])
def test_malformed(bad):
    with pytest.raises(LLMBadResponse) as ei:
        parse_response(bad)
    assert ei.value.code == "llm_bad_response"


def test_json_schema_marks_all_fields_required():
    schema = LLMResponse.model_json_schema()
    assert set(schema["required"]) == {"message", "trades", "watchlist_changes"}
    defs = schema["$defs"]
    assert set(defs["TradeInstruction"]["required"]) == {"ticker", "side", "quantity"}
    assert defs["TradeInstruction"]["properties"]["side"]["enum"] == ["buy", "sell"]
    assert defs["WatchlistInstruction"]["properties"]["action"]["enum"] == ["add", "remove"]
