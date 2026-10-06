import { describe, expect, it } from "vitest";
import { pnlColor, squarify } from "./treemap";

describe("squarify", () => {
  it("rect areas are proportional to values and fill the box", () => {
    const rects = squarify(
      [{ value: 6, data: "a" }, { value: 3, data: "b" }, { value: 1, data: "c" }, { value: 0, data: "zero" }],
      100,
      50,
    );
    expect(rects.map((r) => r.data).sort()).toEqual(["a", "b", "c"]);
    const area = (d: string) => { const r = rects.find((x) => x.data === d)!; return r.w * r.h; };
    expect(area("a")).toBeCloseTo(3000);
    expect(area("b")).toBeCloseTo(1500);
    expect(area("c")).toBeCloseTo(500);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(-1e-9);
      expect(r.y).toBeGreaterThanOrEqual(-1e-9);
      expect(r.x + r.w).toBeLessThanOrEqual(100 + 1e-6);
      expect(r.y + r.h).toBeLessThanOrEqual(50 + 1e-6);
    }
  });
  it("empty for no data or zero size", () => {
    expect(squarify([], 10, 10)).toEqual([]);
    expect(squarify([{ value: 1, data: 1 }], 0, 10)).toEqual([]);
  });
});

describe("pnlColor", () => {
  it("green for gains, red for losses, grey when unknown", () => {
    const g = pnlColor(5).match(/\d+/g)!.map(Number);
    const r = pnlColor(-5).match(/\d+/g)!.map(Number);
    expect(g[1]).toBeGreaterThan(g[0]);
    expect(r[0]).toBeGreaterThan(r[1]);
    expect(pnlColor(null)).toBe("rgb(48, 54, 61)");
  });
});
