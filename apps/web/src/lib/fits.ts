// "Fits Your Week": keep only listings that sit inside the student's free time over the next 7 days,
// from GET /profiles/{id}/schedule/free-blocks, and say which free block each one fits in.
// Campus listings and class times are both Pacific, whatever the browser's zone is.
import { useEffect, useState } from "react";
import type {
  FreeDay,
  RankedOpportunity,
  ScheduledClass,
  ScheduleTerm,
  Weekday,
} from "@hindsight/contracts";
import { api } from "./api";

const PACIFIC = "America/Los_Angeles";
const DAY_MS = 24 * 60 * 60 * 1000;
const parts = new Intl.DateTimeFormat("en-US", {
  timeZone: PACIFIC,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const DAY_NAME: Record<Weekday, string> = {
  Mon: "Monday",
  Tue: "Tuesday",
  Wed: "Wednesday",
  Thu: "Thursday",
  Fri: "Friday",
  Sat: "Saturday",
  Sun: "Sunday",
};

/** A moment as its Pacific date ("2026-10-27") and minutes after midnight. */
function pacific(at: number): { date: string; minutes: number } {
  const p = Object.fromEntries(parts.formatToParts(new Date(at)).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute) };
}

const minutesOf = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h! * 60 + m!;
};

// "2 PM", "9:30 AM"; with `meridiem` false, "2", "9:30".
function clock(mins: number, meridiem: boolean): string {
  const h = Math.floor(mins / 60) % 24;
  const m = mins % 60;
  const text = `${h % 12 || 12}${m ? `:${String(m).padStart(2, "0")}` : ""}`;
  return meridiem ? `${text} ${h < 12 ? "AM" : "PM"}` : text;
}

/** "2–5 PM", or "11 AM–1 PM" when the halves differ. */
export function span(start: string, end: string): string {
  const s = minutesOf(start);
  const e = minutesOf(end);
  const same = s < 720 === e < 720;
  return `${clock(s, !same)}–${clock(e, true)}`;
}

/** Monday of the week that holds this Pacific date, as "YYYY-MM-DD". */
function mondayOf(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const utc = Date.UTC(y!, m! - 1, d!);
  const weekday = (new Date(utc).getUTCDay() + 6) % 7;
  return new Date(utc - weekday * DAY_MS).toISOString().slice(0, 10);
}

/** The next 7 days, starting today (Pacific): what the toggle covers, and the API's from/to. */
export function nextSevenDays(now: number): { from: string; to: string } {
  return { from: pacific(now).date, to: pacific(now + 6 * DAY_MS).date };
}

// The term that's running today, else the next to start, else the latest (as the Schedule page picks).
function currentTerm(rows: ScheduledClass[], terms: ScheduleTerm[], today: string): string | undefined {
  const dated = (t: string) => rows.filter((r) => r.term === t && r.start_date && r.end_date);
  const running = terms.find((t) =>
    dated(t.term).some((r) => r.start_date! <= today && today <= r.end_date!),
  );
  if (running) return running.term;
  const next = terms.find((t) => dated(t.term).some((r) => r.start_date! > today));
  return next?.term ?? terms[terms.length - 1]?.term;
}

export type FreeWeek =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "no-schedule" }
  | { status: "ready"; days: Map<string, FreeDay>; term?: string };

/** Free days over the next 7 days (one or two calendar weeks), once `enabled`. */
export function useFreeWeek(profileId: string | undefined, enabled: boolean, now: number): FreeWeek {
  const [state, setState] = useState<FreeWeek>({ status: "loading" });
  const { from, to } = nextSevenDays(now);
  useEffect(() => {
    if (!profileId || !enabled) return;
    let live = true;
    setState({ status: "loading" });
    (async () => {
      const saved = await api.schedule(profileId);
      if (!saved.rows.length) return { status: "no-schedule" } as const;
      const term = currentTerm(saved.rows, saved.terms ?? [], from);
      const weeks = [...new Set([mondayOf(from), mondayOf(to)])];
      const responses = await Promise.all(weeks.map((w) => api.freeBlocks(profileId, w, term)));
      const days = new Map(responses.flatMap((r) => r.days).map((d) => [d.date, d] as const));
      return { status: "ready", days, term } as const;
    })().then(
      (next) => live && setState(next),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [profileId, enabled, from, to]);
  return state;
}

/**
 * Why a listing fits: "Free Tuesday 2–5 PM", for one that starts and ends on the same day inside a
 * free block. Listings without both a start and an end time can't be checked, so they don't fit.
 */
export function fitFor(item: RankedOpportunity, days: Map<string, FreeDay>, now: number): string | undefined {
  if (!item.starts_at || !item.ends_at) return undefined;
  const start = Date.parse(item.starts_at);
  const end = Date.parse(item.ends_at);
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start || start < now) return undefined;
  const s = pacific(start);
  const e = pacific(end);
  if (s.date !== e.date) return undefined;
  const day = days.get(s.date);
  const block = day?.blocks.find(
    (b) => minutesOf(b.start) <= s.minutes && e.minutes <= minutesOf(b.end),
  );
  return day && block ? `Free ${DAY_NAME[day.day]} ${span(block.start, block.end)}` : undefined;
}
