import type { Profile } from "@hindsight/contracts";
import { SJSU_NAME } from "./config";

// For profiles saved before the API sent institution names.
const CAMPUS_LONG: Record<string, string> = { sjsu: SJSU_NAME, berkeley: "University of California, Berkeley" };

/** "San Jose State University" → "SJSU", "University of California, Los Angeles" → "UCLA",
 *  "California State University, East Bay" → "CSU East Bay"; anything else as is. */
export function shortUniversity(name: string): string {
  if (/^San Jos[eé] State University$/.test(name)) return "SJSU";
  const uc = /^University of California,\s*(.+)$/.exec(name)?.[1];
  if (uc) return uc === "Los Angeles" ? "UCLA" : `UC ${uc}`;
  const csu = /^California State University,\s*(.+)$/.exec(name)?.[1];
  return csu ? `CSU ${csu}` : name;
}

/** "De Anza College" → "De Anza" */
export const shortCollege = (name: string) => name.replace(/ College$/, "");

/** The student's university, full name: ASSIST's, or the campus's for an older saved profile. */
export const universityName = (p: Pick<Profile, "campus" | "receiving_institution_name">) =>
  p.receiving_institution_name ?? CAMPUS_LONG[p.campus] ?? "your university";

/** The student's community college, full name. */
export const collegeName = (p: Pick<Profile, "sending_institution_id" | "sending_institution_name">) =>
  p.sending_institution_name ?? "your community college";

/** "Data Science, B.S." → "Data Science" */
export const shortMajor = (label: string) => label.replace(/,\s*B\.[AS]\.?$/i, "").trim();

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

// A host on a campus's own domain gets that campus beside it; open hackathon sites stay bare.
export function hostWithCampus(host: string): string {
  if (host.endsWith("sjsu.edu")) return `${host} (SJSU)`;
  if (host.endsWith("berkeley.edu")) return `${host} (Berkeley)`;
  return host;
}
