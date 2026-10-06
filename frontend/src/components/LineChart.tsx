"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  BaselineSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { ChartPoint } from "@/lib/prices";

type Kind = "area" | "baseline";

/** Canvas line chart (Lightweight Charts). `resetKey` change → refit the time scale. */
export default function LineChart({
  data,
  kind = "area",
  color = "#209dd7",
  baseValue = 0,
  resetKey,
  secondsVisible = true,
}: {
  data: ChartPoint[];
  kind?: Kind;
  color?: string;
  baseValue?: number;
  resetKey?: string;
  secondsVisible?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | ISeriesApi<"Baseline"> | null>(null);
  const lastKey = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#7d8899",
        fontFamily: '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace',
        fontSize: 10,
        attributionLogo: false,
      },
      grid: { vertLines: { color: "rgba(38,48,64,0.45)" }, horzLines: { color: "rgba(38,48,64,0.45)" } },
      rightPriceScale: { borderColor: "#263040" },
      timeScale: { borderColor: "#263040", timeVisible: true, secondsVisible },
      crosshair: { mode: CrosshairMode.Magnet },
    });
    const series =
      kind === "baseline"
        ? chart.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: baseValue },
            topLineColor: "#26c281",
            topFillColor1: "rgba(38,194,129,0.28)",
            topFillColor2: "rgba(38,194,129,0.02)",
            bottomLineColor: "#f0524f",
            bottomFillColor1: "rgba(240,82,79,0.02)",
            bottomFillColor2: "rgba(240,82,79,0.28)",
            lineWidth: 2,
          })
        : chart.addSeries(AreaSeries, {
            lineColor: color,
            topColor: `${color}55`,
            bottomColor: `${color}05`,
            lineWidth: 2,
          });
    chartRef.current = chart;
    seriesRef.current = series;
    lastKey.current = undefined;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [kind, color, baseValue, secondsVisible]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    if (lastKey.current !== resetKey) {
      chartRef.current?.timeScale().fitContent();
      lastKey.current = resetKey;
    }
  }, [data, resetKey, kind, color, baseValue, secondsVisible]);

  return <div ref={ref} className="h-full w-full" />;
}
