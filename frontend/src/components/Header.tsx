import { fmtSignedUsd, fmtUsd, signClass } from "@/lib/format";
import type { ConnectionState, SourceStatus } from "@/lib/types";

const DOT: Record<ConnectionState, string> = {
  connected: "bg-up shadow-[0_0_8px_var(--color-up)]",
  reconnecting: "bg-accent dot-pulse",
  disconnected: "bg-down",
};
const LABEL: Record<ConnectionState, string> = { connected: "LIVE", reconnecting: "CONNECTING", disconnected: "OFFLINE" };

export default function Header({
  total,
  cash,
  pnl,
  connection,
  source,
}: {
  total: number | null;
  cash: number | null;
  pnl: number | null;
  connection: ConnectionState;
  source: SourceStatus | null;
}) {
  const sourceText = source ? `${source.source}${source.state && source.state !== "ok" ? ` · ${source.state}` : ""}` : "";
  return (
    <header className="flex items-center gap-6 border-b border-line bg-panel-2 px-4 h-14 shrink-0">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-lg font-bold tracking-tight text-accent">FinAlly</span>
        <span className="hidden md:inline text-[10px] font-mono uppercase tracking-[0.2em] text-dim">AI Trading Workstation</span>
      </div>

      <div className="flex items-center gap-6 ml-4">
        <Stat label="Portfolio">
          <span data-testid="header-total-value" className="num text-xl font-semibold text-ink">
            {fmtUsd(total)}
          </span>
        </Stat>
        <Stat label="Cash">
          <span data-testid="header-cash" className="num text-base text-ink">
            {fmtUsd(cash)}
          </span>
        </Stat>
        <Stat label="Unrealized">
          <span className={`num text-base ${signClass(pnl)}`}>{fmtSignedUsd(pnl)}</span>
        </Stat>
      </div>

      <div className="ml-auto flex items-center gap-3 min-w-0">
        {source?.message ? (
          <span className="truncate max-w-[420px] text-[11px] text-accent/90" title={source.message}>
            {source.message}
          </span>
        ) : null}
        <div
          data-testid="connection-status"
          data-state={connection}
          className="flex items-center gap-2 rounded border border-line px-2 py-1 font-mono text-[11px] text-muted"
          title={`Price stream: ${connection}`}
        >
          <span className={`inline-block h-2 w-2 rounded-full ${DOT[connection]}`} />
          <span>{LABEL[connection]}</span>
          {sourceText ? <span className="text-dim uppercase">{sourceText}</span> : null}
        </div>
      </div>
    </header>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col leading-tight">
      <span className="panel-title !text-[9.5px]">{label}</span>
      {children}
    </div>
  );
}
