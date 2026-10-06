import type { Position, Quote } from "./types";

export interface LivePosition {
  ticker: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  pnl_percent: number | null;
  weight: number; // 0..1 of total market value of priced positions
}

/** Live price for a ticker: SSE quote first, then the REST-provided price. */
export function livePrice(ticker: string, quotes: Record<string, Quote>, fallback: number | null = null): number | null {
  const q = quotes[ticker];
  if (q && Number.isFinite(q.price)) return q.price;
  return fallback ?? null;
}

/** Positions re-valued with live SSE prices, plus portfolio weights. */
export function livePositions(positions: readonly Position[], quotes: Record<string, Quote>): LivePosition[] {
  const rows = positions.map((p) => {
    const price = livePrice(p.ticker, quotes, p.price);
    if (price === null) {
      return { ticker: p.ticker, quantity: p.quantity, avg_cost: p.avg_cost, price: null, market_value: null, unrealized_pnl: null, pnl_percent: null, weight: 0 };
    }
    const market_value = p.quantity * price;
    const unrealized_pnl = p.quantity * (price - p.avg_cost);
    const pnl_percent = p.avg_cost > 0 ? ((price - p.avg_cost) / p.avg_cost) * 100 : 0;
    return { ticker: p.ticker, quantity: p.quantity, avg_cost: p.avg_cost, price, market_value, unrealized_pnl, pnl_percent, weight: 0 };
  });
  const total = rows.reduce((s, r) => s + (r.market_value ?? 0), 0);
  for (const r of rows) r.weight = total > 0 && r.market_value !== null ? r.market_value / total : 0;
  return rows;
}

/** Header value: cash + Σ qty × live price. null if any position is unpriced (contract §3). */
export function totalValue(cash: number, positions: readonly Position[], quotes: Record<string, Quote>): number | null {
  let total = cash;
  for (const p of positions) {
    const price = livePrice(p.ticker, quotes, p.price);
    if (price === null) return null;
    total += p.quantity * price;
  }
  return total;
}

/** Total unrealized P&L across priced positions. */
export function totalUnrealized(rows: readonly LivePosition[]): number {
  return rows.reduce((s, r) => s + (r.unrealized_pnl ?? 0), 0);
}
