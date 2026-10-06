"use client";

import { useEffect, useRef, useState } from "react";
import { applyPriceEvent, emptyPriceState, parsePriceEvent, type PriceState } from "@/lib/prices";
import type { ConnectionState, SourceStatus } from "@/lib/types";

/** Subscribes to /api/stream/prices (MARKET_DATA_DESIGN §11.4). EventSource handles reconnects itself. */
export function usePriceStream(url = "/api/stream/prices") {
  const [prices, setPrices] = useState<PriceState>(emptyPriceState);
  const [connection, setConnection] = useState<ConnectionState>("reconnecting");
  const [source, setSource] = useState<SourceStatus | null>(null);
  const stateRef = useRef<PriceState>(prices);

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setConnection("disconnected");
      return;
    }
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      es = new EventSource(url);
      es.onopen = () => setConnection("connected");
      es.onerror = () => {
        if (!es) return;
        if (es.readyState === EventSource.CLOSED) {
          setConnection("disconnected");
          // Browser gave up (e.g. non-200 response); try again ourselves.
          es.close();
          if (!closed) retryTimer = setTimeout(connect, 5000);
        } else {
          setConnection("reconnecting");
        }
      };
      es.onmessage = (e: MessageEvent<string>) => {
        const ev = parsePriceEvent(e.data);
        if (!ev) return;
        setConnection("connected");
        stateRef.current = applyPriceEvent(stateRef.current, ev);
        setPrices(stateRef.current);
        setSource(ev.source ?? null);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [url]);

  return { prices, connection, source };
}
