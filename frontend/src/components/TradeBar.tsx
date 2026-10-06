"use client";

import { useEffect, useState } from "react";
import { fmtPrice } from "@/lib/format";
import type { TradeSide } from "@/lib/types";

export interface TradeOutcome {
  ok: boolean;
  text: string;
}

export default function TradeBar({
  selected,
  livePriceFor,
  onTrade,
}: {
  selected: string | null;
  livePriceFor: (t: string) => number | null;
  onTrade: (ticker: string, side: TradeSide, qty: number) => Promise<TradeOutcome>;
}) {
  const [ticker, setTicker] = useState(selected ?? "");
  const [qty, setQty] = useState("1");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<TradeOutcome | null>(null);

  useEffect(() => {
    if (selected) setTicker(selected);
  }, [selected]);

  const submit = async (side: TradeSide) => {
    const t = ticker.trim().toUpperCase();
    const q = Number(qty);
    if (!t) return setMsg({ ok: false, text: "Enter a ticker" });
    if (!Number.isFinite(q) || q <= 0) return setMsg({ ok: false, text: "Quantity must be greater than 0" });
    setBusy(true);
    try {
      setMsg(await onTrade(t, side, q));
    } finally {
      setBusy(false);
    }
  };

  const price = ticker ? livePriceFor(ticker.trim().toUpperCase()) : null;
  const q = Number(qty);
  const est = price !== null && Number.isFinite(q) && q > 0 ? price * q : null;

  return (
    <section className="flex flex-wrap items-center gap-2 px-3 py-2">
      <span className="panel-title mr-1">Trade</span>
      <input
        data-testid="trade-ticker-input"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        placeholder="TICKER"
        maxLength={10}
        className="w-24 rounded border border-line bg-bg px-2 py-1.5 font-mono text-xs uppercase text-ink placeholder:text-dim focus:border-blue focus:outline-none"
      />
      <input
        data-testid="trade-quantity-input"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        type="number"
        min="0"
        step="any"
        placeholder="Qty"
        className="num w-24 rounded border border-line bg-bg px-2 py-1.5 text-xs text-ink placeholder:text-dim focus:border-blue focus:outline-none"
        onKeyDown={(e) => {
          if (e.key === "Enter") submit("buy");
        }}
      />
      <button
        data-testid="trade-buy-button"
        type="button"
        disabled={busy}
        onClick={() => submit("buy")}
        className="rounded bg-purple px-4 py-1.5 text-xs font-bold tracking-wide text-white hover:brightness-125 disabled:opacity-50"
      >
        BUY
      </button>
      <button
        data-testid="trade-sell-button"
        type="button"
        disabled={busy}
        onClick={() => submit("sell")}
        className="rounded border border-purple px-4 py-1.5 text-xs font-bold tracking-wide text-[#c99be0] hover:bg-purple/30 disabled:opacity-50"
      >
        SELL
      </button>
      <span className="num text-[11px] text-dim">{est !== null ? `≈ $${fmtPrice(est)} @ ${fmtPrice(price)}` : ""}</span>
      <span
        data-testid="trade-message"
        data-status={msg ? (msg.ok ? "executed" : "failed") : undefined}
        className={`ml-auto truncate font-mono text-[11px] ${msg ? (msg.ok ? "text-up" : "text-down") : "text-dim"}`}
      >
        {busy ? "Submitting…" : msg?.text ?? ""}
      </span>
    </section>
  );
}
