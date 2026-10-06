"use client";

import { useMemo } from "react";
import LineChart from "./LineChart";
import { fmtSignedUsd, signClass } from "@/lib/format";
import { toChartSeries } from "@/lib/prices";
import type { Snapshot } from "@/lib/types";

export const STARTING_CASH = 10000;
const tzOffsetSec = () => -new Date().getTimezoneOffset() * 60;

export default function PnlChart({ snapshots, liveTotal }: { snapshots: Snapshot[]; liveTotal: number | null }) {
  const data = useMemo(
    () =>
      toChartSeries(
        snapshots
          .map((s) => ({ t: Date.parse(s.recorded_at), value: s.total_value }))
          .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.value)),
        tzOffsetSec(),
      ),
    [snapshots],
  );
  const pnl = liveTotal !== null ? liveTotal - STARTING_CASH : null;
  return (
    <section data-testid="pnl-chart" data-points={data.length} className="flex h-full min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-3 pt-2.5 pb-1">
        <span className="panel-title">Portfolio Value</span>
        <span className={`num text-xs ${signClass(pnl)}`}>
          {fmtSignedUsd(pnl)} <span className="text-dim">vs $10k</span>
        </span>
      </div>
      <div className="relative min-h-0 flex-1 px-1 pb-1">
        {data.length === 0 ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center font-mono text-[11px] text-dim pointer-events-none">
            Waiting for first snapshot…
          </div>
        ) : null}
        <LineChart data={data} kind="baseline" baseValue={STARTING_CASH} resetKey={String(data.length > 0)} />
      </div>
    </section>
  );
}
