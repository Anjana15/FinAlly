import type { PriceEvent, Quote } from "./types";

/** Max points kept per ticker (MARKET_DATA_DESIGN §11.4 / REVIEW §5). */
export const MAX_POINTS = 600;

export interface PricePoint {
  /** client receipt time, ms since epoch */
  t: number;
  price: number;
}

export interface FlashMark {
  dir: "up" | "down";
  /** monotonically increasing; used as a React key to restart the CSS fade */
  seq: number;
}

export interface PriceState {
  quotes: Record<string, Quote>;
  /** last price seen by this client, per ticker */
  last: Record<string, number>;
  history: Record<string, PricePoint[]>;
  flashes: Record<string, FlashMark>;
  seq: number;
}

export const emptyPriceState = (): PriceState => ({
  quotes: {},
  last: {},
  history: {},
  flashes: {},
  seq: 0,
});

/** Parse one SSE `data:` payload. Returns null for anything that isn't a prices frame. */
export function parsePriceEvent(data: string): PriceEvent | null {
  try {
    const ev = JSON.parse(data);
    if (!ev || ev.type !== "prices" || typeof ev.quotes !== "object" || ev.quotes === null) return null;
    return ev as PriceEvent;
  } catch {
    return null;
  }
}

/** Flash direction vs. the client's own last price. undefined = no flash (first sighting or unchanged). */
export function flashDirection(prev: number | undefined, next: number): "up" | "down" | undefined {
  if (prev === undefined || prev === next) return undefined;
  return next > prev ? "up" : "down";
}

/** Append a point, dropping the oldest so at most `max` remain. Returns a new array. */
export function appendBounded<T>(arr: readonly T[] | undefined, item: T, max = MAX_POINTS): T[] {
  const base = arr ?? [];
  const out = base.length >= max ? base.slice(base.length - max + 1) : base.slice();
  out.push(item);
  return out;
}

/**
 * Pure reducer for one SSE frame. Every frame is a full snapshot (§11.1):
 * quotes are replaced, and tickers missing from the frame are forgotten.
 * Flash + sparkline append happen only on a real price change vs. the client's
 * last price, so reconnect snapshots and Massive's repeated prices don't flash.
 */
export function applyPriceEvent(state: PriceState, ev: PriceEvent, now = Date.now(), max = MAX_POINTS): PriceState {
  const last: Record<string, number> = {};
  const history: Record<string, PricePoint[]> = {};
  const flashes: Record<string, FlashMark> = {};
  let seq = state.seq;

  for (const q of Object.values(ev.quotes)) {
    if (!q || typeof q.price !== "number" || !Number.isFinite(q.price)) continue;
    const prev = state.last[q.ticker];
    const dir = flashDirection(prev, q.price);
    if (dir) {
      seq += 1;
      flashes[q.ticker] = { dir, seq };
    } else if (state.flashes[q.ticker]) {
      flashes[q.ticker] = state.flashes[q.ticker];
    }
    history[q.ticker] =
      prev !== q.price ? appendBounded(state.history[q.ticker], { t: now, price: q.price }, max) : state.history[q.ticker] ?? [];
    last[q.ticker] = q.price;
  }

  return { quotes: ev.quotes, last, history, flashes, seq };
}

export interface ChartPoint {
  time: number; // seconds
  value: number;
}

/**
 * Convert ms-stamped points to strictly increasing whole-second points
 * (Lightweight Charts requires unique ascending times). Last value in a second wins.
 * `offsetSec` shifts to local wall time since the chart renders UTC.
 */
export function toChartSeries(points: readonly { t: number; value: number }[], offsetSec = 0): ChartPoint[] {
  const out: ChartPoint[] = [];
  for (const p of points) {
    const time = Math.floor(p.t / 1000) + offsetSec;
    const tail = out[out.length - 1];
    if (tail && time <= tail.time) {
      if (time === tail.time) tail.value = p.value;
      continue;
    }
    out.push({ time, value: p.value });
  }
  return out;
}
