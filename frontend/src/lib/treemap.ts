export interface TreemapItem<T> {
  value: number;
  data: T;
}
export interface TreemapRect<T> {
  x: number;
  y: number;
  w: number;
  h: number;
  data: T;
}

function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  const sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

/** Squarified treemap (Bruls et al.) laying items into a w×h box. Zero/negative values are skipped. */
export function squarify<T>(items: readonly TreemapItem<T>[], width: number, height: number): TreemapRect<T>[] {
  const valid = items.filter((i) => i.value > 0 && Number.isFinite(i.value)).sort((a, b) => b.value - a.value);
  const total = valid.reduce((s, i) => s + i.value, 0);
  if (!total || width <= 0 || height <= 0) return [];
  const scale = (width * height) / total;
  const queue = valid.map((i) => ({ area: i.value * scale, data: i.data }));
  const out: TreemapRect<T>[] = [];
  let x = 0, y = 0, w = width, h = height;

  while (queue.length) {
    const side = Math.min(w, h);
    const row: typeof queue = [queue.shift()!];
    while (queue.length) {
      const cur = row.map((r) => r.area);
      const next = [...cur, queue[0].area];
      if (worst(next, side) <= worst(cur, side)) row.push(queue.shift()!);
      else break;
    }
    const rowArea = row.reduce((s, r) => s + r.area, 0);
    if (w >= h) {
      // lay the row as a column on the left
      const colW = rowArea / h;
      let cy = y;
      for (const r of row) {
        const rh = r.area / colW;
        out.push({ x, y: cy, w: colW, h: rh, data: r.data });
        cy += rh;
      }
      x += colW;
      w -= colW;
    } else {
      const rowH = rowArea / w;
      let cx = x;
      for (const r of row) {
        const rw = r.area / rowH;
        out.push({ x: cx, y, w: rw, h: rowH, data: r.data });
        cx += rw;
      }
      y += rowH;
      h -= rowH;
    }
  }
  return out;
}

/** Heatmap colour for a P&L percent: red ← neutral → green, saturating at ±maxPct. */
export function pnlColor(pct: number | null, maxPct = 5): string {
  if (pct === null || !Number.isFinite(pct)) return "rgb(48, 54, 61)";
  const t = Math.max(-1, Math.min(1, pct / maxPct));
  const neutral = [38, 44, 54];
  const target = t >= 0 ? [22, 163, 74] : [220, 38, 38];
  const k = 0.25 + 0.75 * Math.abs(t);
  const mix = neutral.map((n, i) => Math.round(n + (target[i] - n) * k));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}
