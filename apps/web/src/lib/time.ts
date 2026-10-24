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

// Campus listings are in Pacific time, whatever the browser's zone is.
const PACIFIC = "America/Los_Angeles";
const dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: PACIFIC, weekday: "short", month: "short", day: "numeric" });
const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: PACIFIC, hour: "numeric", minute: "2-digit" });
const clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: PACIFIC, hour: "numeric", minute: "numeric", hourCycle: "h23" });

/** Scraped date-only values are stored as midnight Pacific; those carry no real time of day. */
export function isDateOnly(at: Date): boolean {
  const parts = Object.fromEntries(clockFmt.formatToParts(at).map((p) => [p.type, p.value]));
  return Number(parts.hour) === 0 && Number(parts.minute) === 0;
}

/** "Sat, Oct 25 · 6:00 PM" in Pacific time; the time is dropped for date-only values. */
export function formatWhen(iso: string): string | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return isDateOnly(at) ? dateFmt.format(at) : `${dateFmt.format(at)} · ${timeFmt.format(at)}`;
}

/** "Fri, Jan 15" (no time), for ranges of days. */
export function formatDay(iso: string): string | null {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : dateFmt.format(at);
}

/**
 * The date a listing's countdown runs to. A hackathon's scraped "deadline" is the last day of its
 * submission period, so until it starts the number that matters is its start.
 */
export function closeAt(item: { type: string; starts_at?: string; deadline?: string }, now: number): string | undefined {
  if (item.type === "hackathon" && item.starts_at && Date.parse(item.starts_at) > now) return item.starts_at;
  return item.deadline;
}

export type TimeLeft = { value: number; unit: string; urgency: Urgency };

/** The big numeral on a listing: 3 / "Days left", 5 / "Hours left", 0 / "Closed". */
export function timeLeft(iso: string, now: number): TimeLeft | null {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const left = at - now;
  if (left <= 0) return { value: 0, unit: "Closed", urgency: "past" };
  const urgency: Urgency = left < 2 * DAY ? "urgent" : left < 7 * DAY ? "soon" : "later";
  if (left < HOUR) return { value: Math.max(1, Math.floor(left / MINUTE)), unit: "Minutes left", urgency };
  if (left < DAY) return { value: Math.floor(left / HOUR), unit: left < 2 * HOUR ? "Hour left" : "Hours left", urgency };
  const days = Math.floor(left / DAY);
  return { value: days, unit: days === 1 ? "Day left" : "Days left", urgency };
}
