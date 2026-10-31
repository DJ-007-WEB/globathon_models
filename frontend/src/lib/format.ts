// Display formatting only. Never computes analytical values and never turns null into 0.

const MINUS = "−";

export const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

/** Format a number for display; null/undefined/NaN becomes an em dash. */
export function formatNumber(value: unknown, maxFractionDigits = 1): string {
  if (!isNumber(value)) return "—";
  const abs = Math.abs(value);
  // Never round a non-zero value to zero.
  if (abs > 0 && abs < 10 ** -maxFractionDigits) {
    return `${value < 0 ? MINUS : ""}<${(10 ** -maxFractionDigits).toFixed(maxFractionDigits)}`;
  }
  const text = abs.toLocaleString("en-GB", { maximumFractionDigits: maxFractionDigits, minimumFractionDigits: 0 });
  return value < 0 ? `${MINUS}${text}` : text;
}

/** Signed value (explicit plus for positive deltas). */
export function formatSigned(value: unknown, maxFractionDigits = 1): string {
  if (!isNumber(value)) return "—";
  const text = formatNumber(value, maxFractionDigits);
  return value > 0 ? `+${text}` : text;
}

export function formatKwh(value: unknown, maxFractionDigits = 1): string {
  return isNumber(value) ? `${formatNumber(value, maxFractionDigits)} kWh` : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: true });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function formatUtc(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace("T", " ").replace(/:00(\+00:00|Z)$/, " UTC").replace(/(\+00:00|Z)$/, " UTC");
}

export function formatInterval(seconds: number | null | undefined): string {
  if (!isNumber(seconds)) return "—";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

export const humanize = (value: string): string =>
  value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const titleCase = (value: string): string =>
  value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function statusTone(status: string | null | undefined): "success" | "warning" | "danger" | "neutral" {
  switch (status) {
    case "success": case "pass": case "ok": case "available": case "used": return "success";
    case "partial": case "warning": case "not_checked": case "suspected": return "warning";
    case "invalid_input": case "failed": case "fail": case "error": case "unavailable": return "danger";
    default: return "neutral";
  }
}

export const initials = (text: string): string =>
  text.split(/[\s_-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "SS";
