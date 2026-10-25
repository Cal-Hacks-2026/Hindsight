// The campus registry (data/campuses/<ASSIST id>.json), bundled at build time: the same files the API
// reads. The app names no school itself; everything school-specific is looked up here by ASSIST id.
import type { Profile } from "@hindsight/contracts";

export type CampusEntry = {
  assist_id: number;
  name: string;
  short_name: string;
  term_system?: "quarter" | "semester";
  requirements?: string[];
  opportunities?: { feed: string; sources: string; programs?: string };
  university_guide?: { sources: string; guide: string };
};

const files = import.meta.glob<CampusEntry>("../../../../data/campuses/*.json", { eager: true, import: "default" });

const REGISTRY = new Map<number, CampusEntry>(Object.values(files).map((c) => [c.assist_id, c]));

export const campusEntry = (assistId: number | undefined) =>
  assistId === undefined ? undefined : REGISTRY.get(assistId);

const fold = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
const BY_NAME = new Map([...REGISTRY.values()].map((c) => [fold(c.name), c]));

/** For text that names a school but carries no id (an ASSIST citation label): case- and accent-insensitive. */
export const campusNamed = (name: string) => BY_NAME.get(fold(name));

/** Short names of the universities that have a "What to Expect" guide. */
export const guideNames = () =>
  [...REGISTRY.values()].filter((c) => c.university_guide).map((c) => c.short_name);

/** Whether the registry lists opportunity sources for the school. */
export const hasFeed = (assistId: number | undefined) => !!campusEntry(assistId)?.opportunities;

/** Where a listing is, from its campus_id: "At <short>, your target school" before transfer, "At
 *  <short>" after; "At <short>, your college" for the student's own college's feed. */
export function campusLabel(
  campusId: number | undefined,
  p: Pick<Profile, "receiving_institution_id" | "sending_institution_id" | "stage">,
): string | undefined {
  const entry = campusEntry(campusId);
  if (!entry) return undefined;
  if (campusId === p.receiving_institution_id)
    return p.stage === "transferred" ? `At ${entry.short_name}` : `At ${entry.short_name}, your target school`;
  if (campusId === p.sending_institution_id) return `At ${entry.short_name}, your college`;
  return `At ${entry.short_name}`;
}

/** Whether the student's feed has anything to show: their university's or their own college's. */
export const watched = (p: Pick<Profile, "receiving_institution_id" | "sending_institution_id">) =>
  hasFeed(p.receiving_institution_id) || hasFeed(p.sending_institution_id);
