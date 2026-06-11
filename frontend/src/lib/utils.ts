import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function timeAgo(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/**
 * Friendly auction end time in the viewer's own timezone, e.g.
 * "in 5 hours — Saturday, June 14 at 8:52 PM".
 */
export function endsLabel(
  endTs: number | null | undefined,
  rawFallback?: string | null,
): string | null {
  if (!endTs) return rawFallback ?? null;
  const ms = endTs * 1000;
  const absolute = new Date(ms).toLocaleString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const diffMin = Math.round((ms - Date.now()) / 60000);
  if (diffMin <= 0) return `ended — ${absolute}`;
  let rel: string;
  if (diffMin < 60) {
    rel = `in ${diffMin} min`;
  } else if (diffMin < 48 * 60) {
    const h = Math.round(diffMin / 60);
    rel = `in ${h} hour${h === 1 ? "" : "s"}`;
  } else {
    const d = Math.floor(diffMin / 1440);
    const h = Math.round((diffMin % 1440) / 60);
    rel = `in ${d}d${h ? ` ${h}h` : ""}`;
  }
  return `${rel} — ${absolute}`;
}
