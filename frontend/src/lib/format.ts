const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtUsd = (n: number | null | undefined): string => (n === null || n === undefined || !Number.isFinite(n) ? "—" : usd.format(n));

export const fmtPrice = (n: number | null | undefined): string =>
  n === null || n === undefined || !Number.isFinite(n) ? "—" : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtSigned = (n: number | null | undefined, digits = 2): string => {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${s}`;
};

export const fmtSignedUsd = (n: number | null | undefined): string => {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${usd.format(Math.abs(n))}`;
};

export const fmtPct = (n: number | null | undefined): string => (n === null || n === undefined || !Number.isFinite(n) ? "—" : `${fmtSigned(n, 2)}%`);

export const fmtQty = (n: number): string => n.toLocaleString("en-US", { maximumFractionDigits: 4 });

export const signClass = (n: number | null | undefined): string =>
  n === null || n === undefined || n === 0 || !Number.isFinite(n) ? "text-muted" : n > 0 ? "text-up" : "text-down";
