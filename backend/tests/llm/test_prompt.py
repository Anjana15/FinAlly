from __future__ import annotations

from app.llm.prompt import SYSTEM_PROMPT, format_portfolio_context, summarize_actions


def test_system_prompt_mentions_key_rules():
    assert "FinAlly, an AI trading assistant" in SYSTEM_PROMPT
    assert "intent" in SYSTEM_PROMPT


def test_context_with_positions():
    portfolio = {"cash": 8100.25, "total_value": 10012.4, "valuation_complete": True,
                 "positions": [{"ticker": "AAPL", "quantity": 10, "avg_cost": 189.97, "price": 191.2,
                                "market_value": 1912.0, "unrealized_pnl": 12.3, "pnl_percent": 0.65}]}
    text = format_portfolio_context(portfolio, [("AAPL", {"price": 191.2, "change_percent": 1.5}), ("X", None)])
    assert "Cash: $8,100.25" in text
    assert "Total value: $10,012.40" in text
    assert "AAPL: 10 sh @ avg $189.97" in text and "P&L $12.30 (+0.65%)" in text
    assert "weight 19.1%" in text
    assert "AAPL: $191.20 (+1.50% since reference)" in text
    assert "X: no price yet" in text


def test_context_unpriced_position():
    portfolio = {"cash": 100.0, "total_value": None, "valuation_complete": False,
                 "positions": [{"ticker": "ZZ", "quantity": 1.5, "avg_cost": 10.0, "price": None,
                                "market_value": None, "unrealized_pnl": None, "pnl_percent": None}]}
    text = format_portfolio_context(portfolio, [])
    assert "incomplete" in text and "P&L n/a" in text and "(empty)" in text


def test_summarize_actions():
    assert summarize_actions(None) == ""
    assert summarize_actions({"trades": [], "watchlist_changes": [], "error": None}) == ""
    s = summarize_actions({"trades": [{"status": "executed", "ticker": "AAPL", "side": "buy",
                                       "quantity": 1.5, "price": 190.0}],
                           "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "added"}],
                           "error": None})
    assert s == "[Actions: buy 1.5 AAPL executed @ $190.00; watchlist add PYPL: added]"
    assert "llm_unavailable" in summarize_actions({"trades": [], "watchlist_changes": [], "error": "llm_unavailable"})
