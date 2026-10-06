// Wire types — mirror planning/TEAM_CONTRACT.md §3 and MARKET_DATA_DESIGN.md §11.

export type Direction = "up" | "down" | "flat";

export interface Quote {
  ticker: string;
  price: number;
  previous_price: number;
  reference_price: number;
  change: number;
  change_percent: number;
  direction: Direction;
  timestamp: string;
}

export type SourceState = "starting" | "ok" | "degraded" | "error" | "stopped";

export interface SourceStatus {
  source: "simulator" | "massive" | string;
  state: SourceState | string;
  message: string | null;
}

export interface PriceEvent {
  type: "prices";
  source: SourceStatus;
  quotes: Record<string, Quote>;
}

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export interface WatchlistEntry {
  ticker: string;
  quote: Quote | null;
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  pnl_percent: number | null;
}

export interface Portfolio {
  cash: number;
  total_value: number | null;
  valuation_complete: boolean;
  positions: Position[];
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export type TradeSide = "buy" | "sell";

export interface TradeResult {
  status: "executed" | "failed";
  ticker: string;
  side: TradeSide | string;
  quantity: number;
  price?: number;
  executed_at?: string;
  cash_balance?: number;
  error?: string;
  detail?: string;
}

export interface WatchlistChange {
  ticker: string;
  action: "add" | "remove" | string;
  status: "added" | "exists" | "removed" | "not_found" | "failed" | string;
  error?: string;
  detail?: string;
}

export interface ChatActions {
  trades: TradeResult[];
  watchlist_changes: WatchlistChange[];
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  actions: ChatActions | null;
}

export interface ApiErrorBody {
  error: string;
  detail: string;
}
