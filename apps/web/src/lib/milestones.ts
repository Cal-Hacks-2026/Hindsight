// Transfer milestones for Home's This Week and Coming Up, from data/milestones.json: a small, hand-checked list with
// the official page each date comes from. Which universities a milestone is for is data (ASSIST ids),
// never a name here.
import data from "../../../../data/milestones.json";

export type UniversitySystem = "UC" | "CSU";

export type Milestone = {
  id: string;
  /** Who it applies to: one university system, or every student. */
  system: UniversitySystem | "any";
  /** Only for students transferring in this term; undefined = every student. */
  transfer?: string;
  /** Only these universities (ASSIST ids); undefined = the whole system. */
  universities?: number[];
  title: string;
  /** "Oct 1–Nov 30, 2026" */
  dates: string;
  /** YYYY-MM-DD, Pacific; the milestone shows until the end of `closes`. */
  opens: string;
  closes: string;
  why: string;
  action: string;
  url: string;
  source: string;
};

export const MILESTONES = data.milestones as Milestone[];

/** From ASSIST's name for the university, as apps/api/app/services/ge/rules.py university_system. */
export function universitySystem(name: string | undefined): UniversitySystem | undefined {
  const n = (name ?? "").toLowerCase();
  if (n.startsWith("university of california")) return "UC";
  if (n.includes("state university") || n.includes("california polytechnic") || n.includes("cal poly"))
    return "CSU";
  return undefined;
}

/** "Fall 2027", Pacific "YYYY-MM-DD" today. The milestones still open or ahead for this student,
 *  soonest-closing first. */
export function upcomingMilestones(
  university: string | undefined,
  universityId: number,
  transfer: string | undefined,
  today: string,
): Milestone[] {
  const system = universitySystem(university);
  return MILESTONES.filter(
    (m) =>
      (m.system === "any" || m.system === system) &&
      (!m.transfer || m.transfer === transfer) &&
      (!m.universities || m.universities.includes(universityId)) &&
      m.closes >= today,
  ).sort((a, b) => a.closes.localeCompare(b.closes));
}
