import type { Profile } from "@hindsight/contracts";
import { campusEntry, campusNamed } from "./campuses";

/** A university's short name: its registry entry's (by ASSIST id, else by name), else the system's pattern:
 *  "University of California, <Campus>" → "UC <Campus>", "California State University, <Campus>" →
 *  "CSU <Campus>"; anything else as is. */
export function shortUniversity(name: string, assistId?: number): string {
  const entry = campusEntry(assistId) ?? campusNamed(name);
  if (entry) return entry.short_name;
  const uc = /^University of California,\s*(.+)$/.exec(name)?.[1];
  if (uc) return `UC ${uc}`;
  const csu = /^California State University,\s*(.+)$/.exec(name)?.[1];
  return csu ? `CSU ${csu}` : name;
}

/** "<Name> College" → "<Name>" */
export const shortCollege = (name: string) => name.replace(/ College$/, "");

/** The student's university, full name: ASSIST's, or the registry's while ASSIST can't say. */
export const universityName = (p: Pick<Profile, "receiving_institution_id" | "receiving_institution_name">) =>
  p.receiving_institution_name ?? campusEntry(p.receiving_institution_id)?.name ?? "your university";

/** The student's community college, full name. */
export const collegeName = (p: Pick<Profile, "sending_institution_id" | "sending_institution_name">) =>
  p.sending_institution_name ?? "your community college";

/** "Data Science, B.S." → "Data Science" */
export const shortMajor = (label: string) => label.replace(/,\s*B\.[AS]\.?$/i, "").trim();

/** Ends a sentence with a period unless it already ends in one: "… for Computer Science B.S." stays
 *  as is, not "B.S..". */
export const withPeriod = (text: string) => {
  const t = text.trimEnd();
  return /[.!?]$/.test(t) ? t : `${t}.`;
};

/** Majors joined for running text: "Data Science + Economics". */
export const majorsLine = (labels: string[]) => labels.map(shortMajor).join(" + ");

/** The academic term a date falls in: "Fall 2026". */
export function currentTerm(d: Date = new Date()): string {
  const m = d.getMonth();
  const season = m <= 4 ? "Spring" : m <= 6 ? "Summer" : "Fall";
  return `${season} ${d.getFullYear()}`;
}

const longDate = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric" });
const dateline = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });

export const formatLongDate = (d: Date = new Date()) => longDate.format(d);

/** "Saturday, October 24, 2026 · Morning edition" */
export function formatDateline(d: Date = new Date()): string {
  const h = d.getHours();
  const edition = h < 12 ? "Morning" : h < 17 ? "Afternoon" : "Evening";
  return `${dateline.format(d)} · ${edition} edition`;
}

/** Written-out small counts read better in an abstract: "Five", "two". */
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
export const countWord = (n: number, capital = false) => {
  const w = WORDS[n] ?? String(n);
  return capital ? w[0]!.toUpperCase() + w.slice(1) : w;
};

export const plural = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);

/** Long lists keep their first few: "A, B, C +6 more". */
export function collapse(items: string[], sep: string, max = 3): string {
  const shown = items.slice(0, max).join(sep);
  return items.length > max ? `${shown} +${items.length - max} more` : shown;
}

/** "A, B and C" */
export function listing(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}
