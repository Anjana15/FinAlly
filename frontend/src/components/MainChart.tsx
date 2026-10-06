"use client";

import { useMemo } from "react";
import LineChart from "./LineChart";
import { fmtPct, fmtPrice, fmtSigned, signClass } from "@/lib/format";
import { toChartSeries, type PricePoint } from "@/lib/prices";
import type { Quote } from "@/lib/types";

const tzOffsetSec = () => -new Date().getTimezoneOffset() * 60;

export default function MainChart({ ticker, quote, points }: { ticker: string | null; quote: Quote | null; points: PricePoint[] | undefined }) {
  const data = useMemo(() => toChartSeries((points ?? []).map((p) => ({ t: p.t, value: p.price })), tzOffsetSec()), [points]);
  return (
    <section data-testid="main-chart" className="flex h-full min-h-0 flex-col">
      <div className="flex items-baseline gap-4 px-3 pt-2.5 pb-1">
        <span className="panel-title">Chart</span>
        <span data-testid="selected-ticker" className="font-mono text-lg font-bold text-accent">
          {ticker ?? "—"}
        </span>
        {quote ? (
          <>
            <span className="num text-lg text-ink">{fmtPrice(quote.price)}</span>
            <span className={`num text-sm ${signClass(quote.change)}`}>
              {fmtSigned(quote.change)} ({fmtPct(quote.change_percent)})
            </span>
            <span className="font-mono text-[10px] text-dim">since session open</span>
          </>
        ) : null}
      </div>
      <div className="relative min-h-0 flex-1 px-1 pb-1">
        {data.length < 2 ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center font-mono text-[11px] text-dim pointer-events-none">
            {ticker ? "Accumulating ticks…" : "Select a ticker"}
          </div>
        ) : null}
        <LineChart data={data} kind="area" color="#209dd7" resetKey={ticker ?? ""} />
      </div>
    </section>
  );
}
