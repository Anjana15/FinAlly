"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fmtPct } from "@/lib/format";
import type { LivePosition } from "@/lib/portfolio";
import { pnlColor, squarify } from "@/lib/treemap";

/** Treemap: rectangle area = portfolio weight, colour = unrealized P&L %. */
export default function Heatmap({ rows, onSelect }: { rows: LivePosition[]; onSelect: (t: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rects = useMemo(
    () => squarify(rows.filter((r) => r.market_value !== null).map((r) => ({ value: r.market_value as number, data: r })), size.w, size.h),
    [rows, size.w, size.h],
  );

  return (
    <section data-testid="portfolio-heatmap" className="flex h-full min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-3 pt-2.5 pb-1">
        <span className="panel-title">Heatmap</span>
        <span className="font-mono text-[10px] text-dim">size = weight · color = P&amp;L</span>
      </div>
      <div ref={ref} className="relative min-h-0 flex-1 mx-2 mb-2">
        {rows.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center rounded border border-dashed border-line font-mono text-[11px] text-dim">
            No positions yet
          </div>
        ) : null}
        {rows.length > 0 && rects.length === 0 ? (
          <div className="absolute inset-0 flex flex-wrap content-start gap-1">
            {rows.map((r) => (
              <span key={r.ticker} className="rounded px-1.5 py-0.5 font-mono text-[11px] text-white" style={{ backgroundColor: pnlColor(r.pnl_percent) }}>
                {r.ticker}
              </span>
            ))}
          </div>
        ) : null}
        {rects.map((r) => {
          const small = r.w < 56 || r.h < 34;
          return (
            <button
              type="button"
              key={r.data.ticker}
              data-testid={`heatmap-cell-${r.data.ticker}`}
              onClick={() => onSelect(r.data.ticker)}
              title={`${r.data.ticker} · ${(r.data.weight * 100).toFixed(1)}% · ${fmtPct(r.data.pnl_percent)}`}
              className="absolute overflow-hidden border border-bg text-left transition-[background-color] duration-500 hover:brightness-125"
              style={{ left: r.x, top: r.y, width: r.w, height: r.h, backgroundColor: pnlColor(r.data.pnl_percent) }}
            >
              <div className="p-1.5 leading-tight">
                <div className="font-mono text-[12px] font-bold text-white">{r.data.ticker}</div>
                {!small ? (
                  <>
                    <div className="num text-[11px] text-white/90">{fmtPct(r.data.pnl_percent)}</div>
                    <div className="num text-[10px] text-white/60">{(r.data.weight * 100).toFixed(1)}%</div>
                  </>
                ) : null}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
