// The student's chosen class sections, from the Schedule feature's GET /profiles/{id}/schedule.
// The plan reads it to fill each planned course's section, professor, days and times. Until that
// endpoint ships (or when it fails) the map is empty and the plan says "Pick a Section".
// Mirrors ScheduledClass / ScheduleResponse ("Class schedule (SCHEDULE)" in packages/contracts);
// switch to those types once they merge.
import { useEffect, useState } from "react";
import { API_URL } from "./config";

export type ScheduledClass = {
  term: string;
  /** As the college prints it: "MATH 1B", or with a campus letter, "MATH D001B". */
  course: string;
  title?: string;
  crn?: string;
  section?: string;
  professor?: string;
  units?: number;
  location?: string;
  mode?: "in_person" | "online" | "hybrid" | "asynchronous";
  /** "Mon".."Sun"; empty for asynchronous or TBA classes. */
  days?: string[];
  /** 24-hour "HH:MM". */
  start_time?: string;
  end_time?: string;
};

/** "MATH D001B", "MATH 1B", "math-1b" → "MATH1B": no spaces or dashes, no campus letter or leading zeros. */
export function courseKey(code: string): string {
  const [prefix = "", ...rest] = code.toUpperCase().replace(/-/g, " ").trim().split(/\s+/);
  const number = rest.join("").replace(/^[A-Z](?=\d)/, "").replace(/^0+(?=\d)/, "");
  return prefix + number;
}

const slotKey = (term: string, code: string) => `${term.trim().toLowerCase()}|${courseKey(code)}`;

export type Schedule = Map<string, ScheduledClass>;

export const scheduledFor = (schedule: Schedule, term: string, code: string) =>
  schedule.get(slotKey(term, code));

const cache = new Map<string, Promise<Schedule>>();

function load(profileId: string): Promise<Schedule> {
  let promise = cache.get(profileId);
  if (!promise) {
    promise = fetch(`${API_URL}/profiles/${encodeURIComponent(profileId)}/schedule`)
      .then((res) => (res.ok ? res.json() : { rows: [] }))
      .then((body: { rows?: unknown }) => {
        const rows = Array.isArray(body?.rows) ? (body.rows as ScheduledClass[]) : [];
        return new Map(
          rows
            .filter((r) => typeof r?.term === "string" && typeof r?.course === "string")
            .map((r) => [slotKey(r.term, r.course), r] as const),
        );
      })
      // No schedule yet is the normal case, not an error the student can act on.
      .catch(() => new Map());
    cache.set(profileId, promise);
  }
  return promise;
}

export function useSchedule(profileId: string): Schedule {
  const [schedule, setSchedule] = useState<Schedule>(() => new Map());
  useEffect(() => {
    let live = true;
    load(profileId).then((s) => live && setSchedule(s));
    return () => {
      live = false;
    };
  }, [profileId]);
  return schedule;
}

/** "09:30" → "9:30", with "AM"/"PM" only where the period changes: "9:30–11:20 AM", "11:30 AM–12:20 PM". */
export function timeRange(start?: string, end?: string): string | undefined {
  const parse = (t?: string) => {
    const m = /^(\d{1,2}):(\d{2})/.exec(t ?? "");
    if (!m) return undefined;
    const h = Number(m[1]);
    return { text: `${h % 12 || 12}:${m[2]}`, period: h < 12 ? "AM" : "PM" };
  };
  const a = parse(start);
  const b = parse(end);
  if (!a) return undefined;
  if (!b) return `${a.text} ${a.period}`;
  return a.period === b.period
    ? `${a.text}–${b.text} ${b.period}`
    : `${a.text} ${a.period}–${b.text} ${b.period}`;
}
