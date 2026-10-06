from __future__ import annotations

import pytest

from app.llm.mock import DEFAULT_MESSAGE, mock_response


def test_buy():
    r = mock_response("buy 2 AAPL")
    assert r.message == "Placing a buy order for 2 AAPL."
    assert [t.model_dump() for t in r.trades] == [{"ticker": "AAPL", "side": "buy", "quantity": 2.0}]
    assert r.watchlist_changes == []


def test_sell():
    r = mock_response("sell 5 TSLA")
    assert r.message == "Placing a sell order for 5 TSLA."
    assert [t.model_dump() for t in r.trades] == [{"ticker": "TSLA", "side": "sell", "quantity": 5.0}]


def test_add():
    r = mock_response("add PYPL")
    assert r.message == "Adding PYPL to your watchlist."
    assert r.trades == []
    assert [w.model_dump() for w in r.watchlist_changes] == [{"ticker": "PYPL", "action": "add"}]


def test_remove():
    r = mock_response("remove NFLX")
    assert r.message == "Removing NFLX from your watchlist."
    assert [w.model_dump() for w in r.watchlist_changes] == [{"ticker": "NFLX", "action": "remove"}]


@pytest.mark.parametrize("text", ["hello", "how is my portfolio?", "buy AAPL", "sell lots of TSLA", ""])
def test_fallback(text):
    r = mock_response(text)
    assert r.message == DEFAULT_MESSAGE
    assert r.trades == [] and r.watchlist_changes == []


@pytest.mark.parametrize("text", ["BUY 2 aapl", "Buy 2 Aapl", "please buy 2 aapl now"])
def test_case_insensitive(text):
    r = mock_response(text)
    assert r.message == "Placing a buy order for 2 AAPL."
    assert r.trades[0].ticker == "AAPL"


def test_case_insensitive_watchlist():
    assert mock_response("ADD pypl").watchlist_changes[0].ticker == "PYPL"
    assert mock_response("Remove pypl").watchlist_changes[0].action == "remove"


def test_fractional_quantity():
    r = mock_response("buy 1.5 AAPL")
    assert r.message == "Placing a buy order for 1.5 AAPL."
    assert r.trades[0].quantity == 1.5


def test_first_rule_wins():
    # buy is checked before sell, and trades before watchlist rules
    r = mock_response("sell 1 TSLA and buy 2 AAPL")
    assert r.trades[0].side == "buy" and r.trades[0].ticker == "AAPL"
    r = mock_response("add PYPL then buy 3 MSFT")
    assert r.trades[0].ticker == "MSFT" and r.watchlist_changes == []
    r = mock_response("remove NFLX and add PYPL")
    assert r.watchlist_changes[0].action == "add"


def test_dotted_ticker():
    assert mock_response("buy 1 brk.b").trades[0].ticker == "BRK.B"


def test_words_containing_keywords_do_not_match():
    assert mock_response("rebuy 2 AAPL").message == DEFAULT_MESSAGE
    assert mock_response("address AAPL").message == DEFAULT_MESSAGE
