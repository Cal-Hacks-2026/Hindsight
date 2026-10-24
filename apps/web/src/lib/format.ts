import type { Campus } from "@hindsight/contracts";

export const CAMPUS_SHORT: Record<Campus, string> = { sjsu: "SJSU", berkeley: "UC Berkeley" };
export const CAMPUS_LONG: Record<Campus, string> = { sjsu: "San José State University", berkeley: "UC Berkeley" };
export const SENDING_LONG = "De Anza College";

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

/** Initial + surname for a byline: "Atishay Pahadiya" → "A. Pahadiya"; one name stays as is. */
export function bylineName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length < 2 ? name.trim() : `${parts[0]![0]}. ${parts.slice(1).join(" ")}`;
}

/** Written-out small counts read better in an abstract: "Five", "two". */
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
export const countWord = (n: number, capital = false) => {
  const w = WORDS[n] ?? String(n);
  return capital ? w[0]!.toUpperCase() + w.slice(1) : w;
};

export const plural = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);

/** "A, B and C" */
export function listing(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}
