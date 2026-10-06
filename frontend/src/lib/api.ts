import type { ChatMessage, Portfolio, Quote, Snapshot, TradeResult, TradeSide, WatchlistEntry } from "./types";

export class ApiError extends Error {
  constructor(public code: string, public detail: string, public status: number) {
    super(detail || code);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("network_error", "Cannot reach the server", 0);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    const b = (body ?? {}) as { error?: string; detail?: unknown };
    const detail = typeof b.detail === "string" ? b.detail : `Request failed (${res.status})`;
    throw new ApiError(b.error ?? `http_${res.status}`, detail, res.status);
  }
  return body as T;
}

export const api = {
  watchlist: () => request<{ tickers: WatchlistEntry[] }>("/api/watchlist"),
  addTicker: (ticker: string) =>
    request<{ ticker: string; status: "added" | "exists"; quote: Quote | null }>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),
  removeTicker: (ticker: string) =>
    request<{ ticker: string; status: "removed" }>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  portfolio: () => request<Portfolio>("/api/portfolio"),
  trade: (ticker: string, side: TradeSide, quantity: number) =>
    request<TradeResult>("/api/portfolio/trade", { method: "POST", body: JSON.stringify({ ticker, side, quantity }) }),
  history: (limit = 500) => request<{ snapshots: Snapshot[] }>(`/api/portfolio/history?limit=${limit}`),
  chatHistory: (limit = 50) => request<{ messages: ChatMessage[] }>(`/api/chat/history?limit=${limit}`),
  chat: (message: string) => request<ChatMessage>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
};
