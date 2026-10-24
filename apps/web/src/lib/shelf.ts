// Bookshelf helpers (DESIGN.md §7): spine colors by department or listing type, and stable sizes.
// Color lives inside the spines; the page itself stays neutral.

const DEPARTMENT: Record<string, string> = {
  ECON: "#7A3E2E",
  MATH: "#26324F",
  STAT: "#3E5A47",
  DATA: "#3E5A47",
  ENGL: "#C9B48A",
  CS: "#4A4458",
  CIS: "#4A4458",
  PHIL: "#6E5528",
  BUS2: "#6E5528",
  SOCI: "#6E5528",
};

const LISTING: Record<string, string> = {
  hackathon: "#26324F",
  workshop: "#7A3E2E",
  event: "#7A3E2E",
  club: "#3E5A47",
  program: "#C9B48A",
  position: "#4A4458",
};

const NEUTRAL = "#5E5B55";

/** Light spines (ENGL's tan) take ink text; the rest take paper. */
const LIGHT = new Set(["#C9B48A"]);

export const departmentOf = (code: string) => code.split(" ")[0]?.toUpperCase() ?? "";
export const departmentColor = (code: string) => DEPARTMENT[departmentOf(code)] ?? NEUTRAL;
export const listingColor = (type: string) => LISTING[type] ?? NEUTRAL;
export const isLight = (color: string) => LIGHT.has(color);

export const LISTING_LEGEND: { label: string; color: string }[] = [
  { label: "Hackathons", color: LISTING.hackathon },
  { label: "Workshops & events", color: LISTING.workshop },
  { label: "Clubs", color: LISTING.club },
  { label: "Programs", color: LISTING.program },
  { label: "Positions", color: LISTING.position },
];

/** Deterministic 0..1 from a string, so a spine keeps its height across renders. */
function unit(key: string): number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 1000) / 1000;
}

export const spineHeight = (key: string, min: number, max: number) => Math.round(min + unit(key) * (max - min));

/** Wider books carry more units. */
export const spineWidth = (units: number | undefined) =>
  units ? Math.round(Math.min(56, Math.max(38, 31 + units * 4))) : 42;

// "MATH 30", "STAT C1000", "ENGL 1B", "BUS2 90"
const CODE_RE = /\b([A-Z][A-Z0-9]{1,5}) (C?\d+[A-Z]{0,3})\b/g;

export type ParsedCourse = { code: string; title: string; alternatives: string[]; choose: boolean };

/**
 * ASSIST receiving-course text → display parts:
 * "MATH 30 - Calculus I" · "ENGL 1B - Argument and Analysis or ENGL 2 - …" · "Choose from: CS 22A - …; CS 47 - …".
 */
export function parseReceiving(text: string): ParsedCourse {
  const codes = [...text.matchAll(CODE_RE)].map((m) => `${m[1]} ${m[2]}`);
  const choose = /^choose from/i.test(text.trim());
  if (choose || codes.length === 0) {
    return { code: choose ? "Elective" : text, title: "", alternatives: codes, choose };
  }
  const first = text.split(/ or (?=[A-Z][A-Z0-9]{1,5} C?\d)/)[0] ?? text;
  const title = first.includes(" - ") ? first.slice(first.indexOf(" - ") + 3).trim() : "";
  return { code: codes[0]!, title, alternatives: codes.slice(1), choose };
}
