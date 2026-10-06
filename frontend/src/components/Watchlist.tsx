"use client";

import { useState } from "react";
import Sparkline from "./Sparkline";
import { fmtPct, fmtPrice, signClass } from "@/lib/format";
import type { FlashMark, PricePoint } from "@/lib/prices";
import type { Quote } from "@/lib/types";

export interface WatchlistProps {
  tickers: string[];
  quotes: Record<string, Quote>;
  fallbackQuotes: Record<string, Quote | null>;
  history: Record<string, PricePoint[]>;
  flashes: Record<string, FlashMark>;
  selected: string | null;
  onSelect: (t: string) => void;
  onAdd: (t: string) => Promise<string | null>; // returns error text or null
  onRemove: (t: string) => void;
}

export default function Watchlist(props: WatchlistProps) {
  const { tickers, quotes, fallbackQuotes, history, flashes, selected, onSelect, onAdd, onRemove } = props;
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    const err = await onAdd(t);
    setBusy(false);
    setError(err);
    if (!err) setInput("");
  };

  return (
    <section data-testid="watchlist" className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between px-3 pt-2.5 pb-2">
        <span className="panel-title">Watchlist</span>
        <span className="font-mono text-[10px] text-dim">{tickers.length}</span>
      </div>
      <form onSubmit={submit} className="flex gap-1.5 px-3 pb-2">
        <input
          data-testid="watchlist-add-input"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="Add ticker"
          maxLength={10}
          className="min-w-0 flex-1 rounded border border-line bg-bg px-2 py-1 font-mono text-xs uppercase text-ink placeholder:normal-case placeholder:text-dim focus:border-blue focus:outline-none"
        />
        <button
          data-testid="watchlist-add-button"
          type="submit"
          disabled={busy}
          className="rounded bg-blue/90 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue disabled:opacity-50"
        >
          Add
        </button>
      </form>
      {error ? <div className="px-3 pb-2 text-[11px] text-down">{error}</div> : null}

      <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 border-y border-line-soft px-3 py-1 font-mono text-[9.5px] uppercase tracking-wider text-dim">
        <span>Sym</span>
        <span className="text-right">Last</span>
        <span className="w-[60px] text-right">Chg%</span>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {tickers.map((t) => {
          const q = quotes[t] ?? fallbackQuotes[t] ?? null;
          const flash = flashes[t];
          const isSel = t === selected;
          return (
            <li
              key={t}
              data-testid={`watchlist-row-${t}`}
              onClick={() => onSelect(t)}
              className={`group relative cursor-pointer border-b border-line-soft px-3 py-1.5 hover:bg-panel-2 ${
                isSel ? "bg-panel-2 shadow-[inset_2px_0_0_var(--color-accent)]" : ""
              }`}
            >
              <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-2">
                <span className={`font-mono text-[13px] font-semibold ${isSel ? "text-accent" : "text-ink"}`}>{t}</span>
                <span
                  key={flash ? flash.seq : "none"}
                  data-testid={`price-${t}`}
                  className={`num rounded px-1 text-right text-[13px] ${flash ? (flash.dir === "up" ? "flash-up" : "flash-down") : ""}`}
                >
                  {q ? fmtPrice(q.price) : "—"}
                </span>
                <span className={`num w-[60px] text-right text-[12px] ${signClass(q?.change_percent)}`}>{q ? fmtPct(q.change_percent) : "—"}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between">
                <Sparkline points={history[t]} width={150} height={20} />
                <button
                  data-testid={`watchlist-remove-${t}`}
                  type="button"
                  aria-label={`Remove ${t}`}
                  title={`Remove ${t}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(t);
                  }}
                  className="rounded px-1.5 font-mono text-[11px] text-dim opacity-60 hover:bg-down/20 hover:text-down group-hover:opacity-100"
                >
                  ✕
                </button>
              </div>
            </li>
          );
        })}
        {tickers.length === 0 ? <li className="px-3 py-4 text-xs text-dim">No tickers. Add one above.</li> : null}
      </ul>
    </section>
  );
}
