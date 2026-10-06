"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ChatPanel from "./ChatPanel";
import Header from "./Header";
import Heatmap from "./Heatmap";
import MainChart from "./MainChart";
import PnlChart from "./PnlChart";
import PositionsTable from "./PositionsTable";
import TradeBar, { type TradeOutcome } from "./TradeBar";
import Watchlist from "./Watchlist";
import { usePriceStream } from "@/hooks/usePriceStream";
import { ApiError, api } from "@/lib/api";
import { fmtPrice, fmtQty } from "@/lib/format";
import { livePositions, livePrice, totalUnrealized, totalValue } from "@/lib/portfolio";
import type { ChatMessage, Portfolio, Quote, Snapshot, TradeSide } from "@/lib/types";

const errText = (e: unknown) => (e instanceof ApiError ? e.detail || e.code : e instanceof Error ? e.message : "Request failed");

export default function Terminal() {
  const { prices, connection, source } = usePriceStream();
  const [watch, setWatch] = useState<string[]>([]);
  const [watchQuotes, setWatchQuotes] = useState<Record<string, Quote | null>>({});
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);

  const loadWatchlist = useCallback(async () => {
    try {
      const { tickers } = await api.watchlist();
      setWatch(tickers.map((t) => t.ticker));
      setWatchQuotes(Object.fromEntries(tickers.map((t) => [t.ticker, t.quote])));
      setSelected((cur) => (cur ?? tickers[0]?.ticker ?? null));
    } catch {
      /* keep last state; connection dot shows server health */
    }
  }, []);

  const loadPortfolio = useCallback(async () => {
    try {
      setPortfolio(await api.portfolio());
    } catch {
      /* ignore */
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      setSnapshots((await api.history(500)).snapshots);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshAll = useCallback(() => {
    loadPortfolio();
    loadWatchlist();
    loadHistory();
  }, [loadPortfolio, loadWatchlist, loadHistory]);

  useEffect(() => {
    refreshAll();
    api
      .chatHistory(50)
      .then((r) => setMessages(r.messages))
      .catch(() => {});
    const id = setInterval(() => {
      loadHistory();
      loadPortfolio();
    }, 30_000);
    return () => clearInterval(id);
  }, [refreshAll, loadHistory, loadPortfolio]);

  const quotes = prices.quotes;
  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio]);
  const rows = useMemo(() => livePositions(positions, quotes), [positions, quotes]);
  const total = portfolio ? totalValue(portfolio.cash, positions, quotes) : null;
  const unrealized = portfolio ? totalUnrealized(rows) : null;

  const priceFor = useCallback(
    (t: string) => livePrice(t, quotes, watchQuotes[t]?.price ?? positions.find((p) => p.ticker === t)?.price ?? null),
    [quotes, watchQuotes, positions],
  );

  const onAdd = async (t: string) => {
    try {
      await api.addTicker(t);
      await loadWatchlist();
      setSelected(t);
      return null;
    } catch (e) {
      return errText(e);
    }
  };

  const onRemove = async (t: string) => {
    setWatch((w) => w.filter((x) => x !== t));
    try {
      await api.removeTicker(t);
    } catch {
      /* fall through to resync */
    }
    await loadWatchlist();
    setSelected((cur) => (cur === t ? null : cur));
  };

  const onTrade = async (ticker: string, side: TradeSide, qty: number): Promise<TradeOutcome> => {
    try {
      const r = await api.trade(ticker, side, qty);
      refreshAll();
      if (r.status === "executed") {
        return { ok: true, text: `${side === "buy" ? "Bought" : "Sold"} ${fmtQty(r.quantity)} ${r.ticker} @ $${fmtPrice(r.price)}` };
      }
      return { ok: false, text: r.detail || r.error || "Trade failed" };
    } catch (e) {
      return { ok: false, text: errText(e) };
    }
  };

  const onSend = async (text: string) => {
    const userMsg: ChatMessage = { id: `local-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString(), actions: null };
    setMessages((m) => [...m, userMsg]);
    setChatLoading(true);
    try {
      const reply = await api.chat(text);
      setMessages((m) => [...m, reply]);
      const a = reply.actions;
      if (a && ((a.trades?.length ?? 0) > 0 || (a.watchlist_changes?.length ?? 0) > 0)) refreshAll();
    } catch (e) {
      setMessages((m) => [
        ...m,
        { id: `err-${Date.now()}`, role: "assistant", content: `Sorry — ${errText(e)}`, created_at: new Date().toISOString(), actions: null },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const selQuote = selected ? quotes[selected] ?? watchQuotes[selected] ?? null : null;

  return (
    <div className="flex h-screen min-h-[640px] flex-col overflow-hidden bg-bg">
      <Header total={total} cash={portfolio?.cash ?? null} pnl={unrealized} connection={connection} source={source} />
      <div className="flex min-h-0 flex-1">
        <aside className="w-[270px] shrink-0 border-r border-line bg-panel">
          <Watchlist
            tickers={watch}
            quotes={quotes}
            fallbackQuotes={watchQuotes}
            history={prices.history}
            flashes={prices.flashes}
            selected={selected}
            onSelect={setSelected}
            onAdd={onAdd}
            onRemove={onRemove}
          />
        </aside>

        <main className="grid min-w-0 flex-1 grid-rows-[minmax(220px,1.25fr)_auto_minmax(200px,1fr)] gap-px bg-line">
          <div className="min-h-0 bg-panel">
            <MainChart ticker={selected} quote={selQuote} points={selected ? prices.history[selected] : undefined} />
          </div>
          <div className="bg-panel-2">
            <TradeBar selected={selected} livePriceFor={priceFor} onTrade={onTrade} />
          </div>
          <div className="grid min-h-0 grid-cols-1 gap-px bg-line lg:grid-cols-[1.1fr_1fr_1fr]">
            <div className="min-h-[180px] bg-panel">
              <PositionsTable rows={rows} onSelect={setSelected} />
            </div>
            <div className="min-h-[180px] bg-panel">
              <Heatmap rows={rows} onSelect={setSelected} />
            </div>
            <div className="min-h-[180px] bg-panel">
              <PnlChart snapshots={snapshots} liveTotal={total} />
            </div>
          </div>
        </main>

        <ChatPanel messages={messages} loading={chatLoading} onSend={onSend} collapsed={chatCollapsed} onToggle={() => setChatCollapsed((c) => !c)} />
      </div>
    </div>
  );
}
