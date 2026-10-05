import pytest

from app.market.cache import PriceCache
from app.market.interface import normalize_ticker
from app.market.models import Direction


def test_first_update_is_flat_and_sets_reference(cache):
    q = cache.update("AAPL", 190.004, source="simulator")
    assert q.price == 190.0 and q.previous_price == 190.0 and q.reference_price == 190.0
    assert q.direction == Direction.FLAT


def test_previous_and_reference_carry_forward(cache, clock):
    cache.update("AAPL", 190.0, source="massive", reference_price=188.0)
    clock.advance(1)
    q = cache.update("AAPL", 191.0, source="massive")
    assert q.previous_price == 190.0 and q.reference_price == 188.0
    assert q.direction == Direction.UP
    assert q.change_percent == pytest.approx(100 * 3 / 188)
    assert q.received_at == clock.t


def test_version_and_remove(cache):
    v0 = cache.version
    cache.update("AAPL", 1.0, source="s")
    cache.remove("AAPL")
    cache.remove("AAPL")  # no-op, no bump
    assert cache.version == v0 + 2 and len(cache) == 0


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_rejects_invalid_prices(cache, bad):
    with pytest.raises(ValueError):
        cache.update("AAPL", bad, source="s")


def test_invalid_reference_falls_back_to_previous(cache):
    cache.update("AAPL", 100.0, source="s", reference_price=90.0)
    q = cache.update("AAPL", 101.0, source="s", reference_price=0)
    assert q.reference_price == 90.0


def test_getters_and_snapshot_copy(cache):
    assert cache.get("AAPL") is None and cache.get_price("AAPL") is None
    cache.update("AAPL", 10.0, source="s")
    assert cache.get_price("AAPL") == 10.0 and "AAPL" in cache
    snap = cache.snapshot()
    cache.update("MSFT", 20.0, source="s")
    assert set(snap) == {"AAPL"}


def test_staleness_age(cache, clock):
    q = cache.update("AAPL", 10.0, source="s")
    clock.advance(7)
    assert q.age(cache.now()) == 7


def test_zero_reference_change_percent_is_zero():
    from app.market.models import PriceQuote

    q = PriceQuote("X", 1.0, 1.0, 0.0, 0.0, 0.0, "s")
    assert q.change_percent == 0.0


def test_to_dict_wire_format():
    c = PriceCache(clock=lambda: 1_759_500_000.5)
    c.update("AAPL", 100.0, source="s")
    d = c.update("AAPL", 99.5, source="s").to_dict()
    assert d == {
        "ticker": "AAPL", "price": 99.5, "previous_price": 100.0, "reference_price": 100.0,
        "change": -0.5, "change_percent": -0.5, "direction": "down",
        "timestamp": "2025-10-03T14:00:00.500Z",
    }


def test_source_status_to_dict():
    from app.market.models import SourceState, SourceStatus

    s = SourceStatus("massive", SourceState.DEGRADED, "hi", 1.0)
    assert s.to_dict() == {"source": "massive", "state": "degraded", "message": "hi"}


@pytest.mark.parametrize("raw,ok", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V")])
def test_normalize_ok(raw, ok):
    assert normalize_ticker(raw) == ok


@pytest.mark.parametrize("raw", ["", "1ABC", "TOOLONGX", "AA PL", ".A"])
def test_normalize_rejects(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)
