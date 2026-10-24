import { useEffect, useState } from "react";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Current time in ms, re-rendering every `intervalMs`. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export type Urgency = "urgent" | "soon" | "later" | "past";

export type Countdown = { label: string; urgency: Urgency };

/** "3 days left", "5 hr left", "Closed" — for a deadline ISO string. */
export function countdown(iso: string, now: number): Countdown | null {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const left = at - now;
  if (left <= 0) return { label: "Closed", urgency: "past" };

  let label: string;
  if (left < HOUR) label = `${Math.max(1, Math.floor(left / MINUTE))} min left`;
  else if (left < DAY) label = `${Math.floor(left / HOUR)} hr left`;
  else {
    const days = Math.floor(left / DAY);
    label = days === 1 ? "1 day left" : `${days} days left`;
  }
  const urgency: Urgency = left < 2 * DAY ? "urgent" : left < 7 * DAY ? "soon" : "later";
  return { label, urgency };
}

const dateFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

/** "Sat, Oct 25 · 6:00 PM"; the time is dropped for date-only values (local midnight). */
export function formatWhen(iso: string): string | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const midnight = at.getHours() === 0 && at.getMinutes() === 0;
  return midnight ? dateFmt.format(at) : `${dateFmt.format(at)} · ${timeFmt.format(at)}`;
}
