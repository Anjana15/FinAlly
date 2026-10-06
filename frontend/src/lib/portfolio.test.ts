import { describe, expect, it } from "vitest";
import { livePositions, livePrice, totalUnrealized, totalValue } from "./portfolio";
import type { Position, Quote } from "./types";

const pos = (ticker: string, quantity: number, avg_cost: number, price: number | null = null): Position => ({
  ticker, quantity, avg_cost, price, market_value: null, unrealized_pnl: null, pnl_percent: null,
});
const quote = (ticker: string, price: number) => ({ ticker, price } as Quote);

describe("portfolio math", () => {
  const quotes = { AAPL: quote("AAPL", 110), MSFT: quote("MSFT", 45) };

  it("livePrice prefers SSE then falls back", () => {
    expect(livePrice("AAPL", quotes, 1)).toBe(110);
    expect(livePrice("TSLA", quotes, 250)).toBe(250);
    expect(livePrice("TSLA", quotes)).toBeNull();
  });

  it("total = cash + Σ qty × live price", () => {
    expect(totalValue(1000, [pos("AAPL", 10, 100), pos("MSFT", 2, 50)], quotes)).toBeCloseTo(1000 + 1100 + 90);
    expect(totalValue(10000, [], {})).toBe(10000);
  });

  it("total is null when a position is unpriced", () => {
    expect(totalValue(1000, [pos("ZZZ", 1, 5)], quotes)).toBeNull();
    expect(totalValue(1000, [pos("ZZZ", 1, 5, 6)], quotes)).toBe(1006);
  });

  it("weights and P&L", () => {
    const rows = livePositions([pos("AAPL", 10, 100), pos("MSFT", 2, 50)], quotes);
    const a = rows.find((r) => r.ticker === "AAPL")!;
    const m = rows.find((r) => r.ticker === "MSFT")!;
    expect(a.market_value).toBe(1100);
    expect(a.unrealized_pnl).toBeCloseTo(100);
    expect(a.pnl_percent).toBeCloseTo(10);
    expect(m.unrealized_pnl).toBeCloseTo(-10);
    expect(m.pnl_percent).toBeCloseTo(-10);
    expect(a.weight + m.weight).toBeCloseTo(1);
    expect(a.weight).toBeCloseTo(1100 / 1190);
    expect(totalUnrealized(rows)).toBeCloseTo(90);
  });

  it("unpriced rows get null values and zero weight", () => {
    const rows = livePositions([pos("ZZZ", 3, 10)], {});
    expect(rows[0]).toMatchObject({ price: null, market_value: null, unrealized_pnl: null, pnl_percent: null, weight: 0 });
  });
});
