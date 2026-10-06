"use client";

import { useEffect, useRef, useState } from "react";
import { fmtPrice, fmtQty } from "@/lib/format";
import type { ChatMessage, TradeResult, WatchlistChange } from "@/lib/types";

const OK_STATUSES = new Set(["executed", "added", "removed", "exists"]);

export function tradeChipText(t: TradeResult): string {
  const base = `${String(t.side).toUpperCase()} ${fmtQty(t.quantity)} ${t.ticker}`;
  if (t.status === "executed") return `${base} @ ${fmtPrice(t.price)}`;
  return `${base} failed: ${t.detail || t.error || "error"}`;
}

export function watchChipText(w: WatchlistChange): string {
  const verb = w.action === "remove" ? "Remove" : "Add";
  switch (w.status) {
    case "added":
      return `${w.ticker} added to watchlist`;
    case "exists":
      return `${w.ticker} already on watchlist`;
    case "removed":
      return `${w.ticker} removed from watchlist`;
    case "not_found":
      return `${w.ticker} not on watchlist`;
    default:
      return `${verb} ${w.ticker} failed: ${w.detail || w.error || "error"}`;
  }
}

function Chip({ status, text }: { status: string; text: string }) {
  const ok = OK_STATUSES.has(status);
  const neutral = status === "exists" || status === "not_found";
  const cls = neutral
    ? "border-line text-muted"
    : ok
      ? "border-up/50 bg-up/10 text-up"
      : "border-down/50 bg-down/10 text-down";
  return (
    <span data-testid="chat-action" data-status={status} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10.5px] ${cls}`}>
      <span>{ok || neutral ? "✓" : "✕"}</span>
      <span>{text}</span>
    </span>
  );
}

export function ChatMessageView({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user";
  const a = m.actions;
  const hasChips = !!a && (a.trades?.length ?? 0) + (a.watchlist_changes?.length ?? 0) > 0;
  return (
    <div data-testid="chat-message" data-role={m.role} className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[92%] whitespace-pre-wrap rounded-md px-2.5 py-1.5 text-[12.5px] leading-relaxed ${
          isUser ? "bg-blue/15 text-ink border border-blue/30" : "bg-panel-2 text-ink border border-line"
        }`}
      >
        {m.content}
      </div>
      {hasChips ? (
        <div className="flex max-w-[92%] flex-wrap gap-1">
          {a!.trades?.map((t, i) => <Chip key={`t${i}`} status={t.status} text={tradeChipText(t)} />)}
          {a!.watchlist_changes?.map((w, i) => <Chip key={`w${i}`} status={w.status} text={watchChipText(w)} />)}
        </div>
      ) : null}
      {a?.error ? <span className="font-mono text-[10px] text-accent">assistant error: {a.error}</span> : null}
    </div>
  );
}

export default function ChatPanel({
  messages,
  loading,
  onSend,
  collapsed,
  onToggle,
}: {
  messages: ChatMessage[];
  loading: boolean;
  onSend: (text: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, loading, collapsed]);

  if (collapsed) {
    return (
      <aside data-testid="chat-panel" data-collapsed="true" className="flex w-10 shrink-0 flex-col items-center border-l border-line bg-panel">
        <button
          type="button"
          onClick={onToggle}
          aria-label="Open AI assistant"
          className="mt-2 flex flex-col items-center gap-2 rounded px-1 py-2 font-mono text-[10px] text-accent hover:bg-panel-2"
        >
          <span>◀</span>
          <span className="[writing-mode:vertical-rl] tracking-[0.2em]">AI COPILOT</span>
        </button>
      </aside>
    );
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || loading) return;
    onSend(t);
    setText("");
  };

  return (
    <aside data-testid="chat-panel" data-collapsed="false" className="flex w-[360px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-3 h-9">
        <span className="panel-title !text-accent">AI Copilot</span>
        <button type="button" onClick={onToggle} aria-label="Collapse AI assistant" className="rounded px-1.5 font-mono text-xs text-dim hover:text-ink">
          ▶
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !loading ? (
          <div className="font-mono text-[11px] leading-relaxed text-dim">
            Ask about your portfolio, or tell me to trade.
            <br />
            e.g. “buy 5 NVDA”, “add PYPL”, “how concentrated am I?”
          </div>
        ) : null}
        {messages.map((m) => (
          <ChatMessageView key={m.id} m={m} />
        ))}
        {loading ? (
          <div data-testid="chat-loading" className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
            <span className="dot-pulse inline-block h-1.5 w-1.5 rounded-full bg-accent" />
            <span className="dot-pulse inline-block h-1.5 w-1.5 rounded-full bg-accent [animation-delay:200ms]" />
            <span className="dot-pulse inline-block h-1.5 w-1.5 rounded-full bg-accent [animation-delay:400ms]" />
            <span className="ml-1">thinking…</span>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
      <form onSubmit={submit} className="flex gap-1.5 border-t border-line p-2">
        <input
          data-testid="chat-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Message FinAlly…"
          className="min-w-0 flex-1 rounded border border-line bg-bg px-2 py-1.5 text-[12.5px] text-ink placeholder:text-dim focus:border-blue focus:outline-none"
        />
        <button
          data-testid="chat-send-button"
          type="submit"
          disabled={loading || !text.trim()}
          className="rounded bg-purple px-3 py-1.5 text-xs font-bold text-white hover:brightness-125 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
