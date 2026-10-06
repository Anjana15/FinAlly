import { fmtPct, fmtPrice, fmtQty, fmtSignedUsd, signClass } from "@/lib/format";
import type { LivePosition } from "@/lib/portfolio";

export default function PositionsTable({ rows, onSelect }: { rows: LivePosition[]; onSelect: (t: string) => void }) {
  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="px-3 pt-2.5 pb-1">
        <span className="panel-title">Positions</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table data-testid="positions-table" className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-panel">
            <tr className="font-mono text-[9.5px] uppercase tracking-wider text-dim">
              <th className="px-3 py-1 text-left font-normal">Sym</th>
              <th className="px-2 py-1 text-right font-normal">Qty</th>
              <th className="px-2 py-1 text-right font-normal">Avg Cost</th>
              <th className="px-2 py-1 text-right font-normal">Price</th>
              <th className="px-2 py-1 text-right font-normal">Unrl P&amp;L</th>
              <th className="px-3 py-1 text-right font-normal">%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.ticker}
                data-testid={`position-row-${r.ticker}`}
                onClick={() => onSelect(r.ticker)}
                className="cursor-pointer border-t border-line-soft hover:bg-panel-2"
              >
                <td className="px-3 py-1 font-mono font-semibold text-ink">{r.ticker}</td>
                <td className="num px-2 py-1 text-right">{fmtQty(r.quantity)}</td>
                <td className="num px-2 py-1 text-right text-muted">{fmtPrice(r.avg_cost)}</td>
                <td className="num px-2 py-1 text-right">{fmtPrice(r.price)}</td>
                <td className={`num px-2 py-1 text-right ${signClass(r.unrealized_pnl)}`}>{fmtSignedUsd(r.unrealized_pnl)}</td>
                <td className={`num px-3 py-1 text-right ${signClass(r.pnl_percent)}`}>{fmtPct(r.pnl_percent)}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center font-mono text-[11px] text-dim">
                  No open positions
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
