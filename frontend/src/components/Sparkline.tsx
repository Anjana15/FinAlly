import type { PricePoint } from "@/lib/prices";

/** Tiny SVG sparkline of points accumulated from SSE since page load. */
export default function Sparkline({ points, width = 84, height = 24 }: { points: PricePoint[] | undefined; width?: number; height?: number }) {
  const pts = points ?? [];
  if (pts.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden>
        <line x1={0} x2={width} y1={height / 2} y2={height / 2} stroke="#263040" strokeDasharray="2 3" />
      </svg>
    );
  }
  let min = Infinity, max = -Infinity;
  for (const p of pts) {
    if (p.price < min) min = p.price;
    if (p.price > max) max = p.price;
  }
  const span = max - min || 1;
  const step = width / (pts.length - 1);
  const d = pts
    .map((p, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)},${(height - 2 - ((p.price - min) / span) * (height - 4)).toFixed(1)}`)
    .join("");
  const up = pts[pts.length - 1].price >= pts[0].price;
  return (
    <svg width={width} height={height} aria-hidden>
      <path d={d} fill="none" stroke={up ? "var(--color-up)" : "var(--color-down)"} strokeWidth={1.25} strokeLinejoin="round" />
    </svg>
  );
}
