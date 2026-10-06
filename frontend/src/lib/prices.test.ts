import { describe, expect, it } from "vitest";
import { appendBounded, applyPriceEvent, emptyPriceState, flashDirection, parsePriceEvent, toChartSeries } from "./prices";
import type { PriceEvent, Quote } from "./types";

const q = (ticker: string, price: number, direction: Quote["direction"] = "flat"): Quote => ({
  ticker, price, previous_price: price, reference_price: 100, change: price - 100, change_percent: price - 100, direction, timestamp: "2026-10-05T14:03:21.512Z",
});
const ev = (...quotes: Quote[]): PriceEvent => ({
  type: "prices",
  source: { source: "simulator", state: "ok", message: null },
  quotes: Object.fromEntries(quotes.map((x) => [x.ticker, x])),
});

describe("parsePriceEvent", () => {
  it("parses a prices frame", () => {
    const parsed = parsePriceEvent(JSON.stringify(ev(q("AAPL", 190))));
    expect(parsed?.quotes.AAPL.price).toBe(190);
    expect(parsed?.source.source).toBe("simulator");
  });
  it("rejects garbage and other frame types", () => {
    expect(parsePriceEvent("not json")).toBeNull();
    expect(parsePriceEvent(JSON.stringify({ type: "other" }))).toBeNull();
    expect(parsePriceEvent(JSON.stringify({ type: "prices" }))).toBeNull();
  });
});

describe("flashDirection", () => {
  it("no flash on first sighting or unchanged price", () => {
    expect(flashDirection(undefined, 10)).toBeUndefined();
    expect(flashDirection(10, 10)).toBeUndefined();
  });
  it("up / down vs. client's last price", () => {
    expect(flashDirection(10, 10.01)).toBe("up");
    expect(flashDirection(10, 9.99)).toBe("down");
  });
});

describe("applyPriceEvent", () => {
  it("first frame: no flash, one history point each", () => {
    const s = applyPriceEvent(emptyPriceState(), ev(q("AAPL", 190, "up"), q("MSFT", 400, "down")), 1000);
    expect(s.flashes).toEqual({});
    expect(s.history.AAPL).toEqual([{ t: 1000, price: 190 }]);
    expect(s.last).toEqual({ AAPL: 190, MSFT: 400 });
  });

  it("flashes only tickers whose price really changed, ignoring server direction", () => {
    let s = applyPriceEvent(emptyPriceState(), ev(q("AAPL", 190), q("MSFT", 400)), 1000);
    s = applyPriceEvent(s, ev(q("AAPL", 191, "flat"), q("MSFT", 400, "up")), 1500);
    expect(s.flashes.AAPL?.dir).toBe("up");
    expect(s.flashes.MSFT).toBeUndefined();
    expect(s.history.AAPL).toHaveLength(2);
    expect(s.history.MSFT).toHaveLength(1); // unchanged price → no new point
    const seq = s.flashes.AAPL!.seq;
    s = applyPriceEvent(s, ev(q("AAPL", 189), q("MSFT", 400)), 2000);
    expect(s.flashes.AAPL).toEqual({ dir: "down", seq: seq + 1 });
  });

  it("drops tickers missing from a frame (full snapshot semantics)", () => {
    let s = applyPriceEvent(emptyPriceState(), ev(q("AAPL", 190), q("MSFT", 400)), 1000);
    s = applyPriceEvent(s, ev(q("AAPL", 190)), 1500);
    expect(Object.keys(s.quotes)).toEqual(["AAPL"]);
    expect(s.last.MSFT).toBeUndefined();
    expect(s.history.MSFT).toBeUndefined();
    // re-added later: treated as first sighting, no flash
    s = applyPriceEvent(s, ev(q("AAPL", 190), q("MSFT", 410)), 2000);
    expect(s.flashes.MSFT).toBeUndefined();
  });

  it("bounds sparkline history", () => {
    let s = emptyPriceState();
    for (let i = 0; i < 50; i++) s = applyPriceEvent(s, ev(q("AAPL", 100 + i)), i * 500, 10);
    expect(s.history.AAPL).toHaveLength(10);
    expect(s.history.AAPL[9].price).toBe(149);
    expect(s.history.AAPL[0].price).toBe(140);
  });
});

describe("appendBounded", () => {
  it("does not mutate and caps length", () => {
    const a = [1, 2, 3];
    const b = appendBounded(a, 4, 3);
    expect(a).toEqual([1, 2, 3]);
    expect(b).toEqual([2, 3, 4]);
    expect(appendBounded(undefined, 1, 3)).toEqual([1]);
  });
});

describe("toChartSeries", () => {
  it("collapses same-second points (last wins) and keeps times strictly increasing", () => {
    const out = toChartSeries([
      { t: 1000, value: 1 },
      { t: 1500, value: 2 },
      { t: 2100, value: 3 },
      { t: 1900, value: 9 }, // out of order → dropped
    ]);
    expect(out).toEqual([
      { time: 1, value: 2 },
      { time: 2, value: 3 },
    ]);
  });
  it("applies timezone offset", () => {
    expect(toChartSeries([{ t: 5000, value: 1 }], 3600)).toEqual([{ time: 3605, value: 1 }]);
  });
});
