// Transfer milestones for Home's This Week: a small, hand-checked list with the official page
// each date comes from (read October 25, 2026). Only this cycle's published dates are listed;
// a later cycle's dates aren't guessed. Add the next cycle once UC, the CSU and CSAC publish it.

export type UniversitySystem = "UC" | "CSU";

export type Milestone = {
  id: string;
  /** Who it applies to: one university system, or every student. */
  system: UniversitySystem | "any";
  /** Only for students transferring in this term; undefined = every student. */
  transfer?: string;
  /** Only these UC campuses ("Davis"); undefined = the whole system. */
  campuses?: string[];
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

const UC_APPLY = "https://admission.universityofcalifornia.edu/how-to-apply/applying-as-a-transfer/";
const UC_TAG =
  "https://admission.universityofcalifornia.edu/admission-requirements/transfer-requirements/uc-transfer-programs/transfer-admission-guarantee-tag.html";
const CSU_DATES = "https://www.calstate.edu/apply/pages/application-dates-deadlines.aspx";
const FAFSA_FORM = "https://studentaid.gov/sites/default/files/2027-28-fafsa-form.pdf";

export const MILESTONES: Milestone[] = [
  {
    id: "uc-tag-fall-2027",
    system: "UC",
    transfer: "Fall 2027",
    campuses: ["Davis", "Irvine", "Merced", "Riverside", "Santa Barbara", "Santa Cruz"],
    title: "Submit a UC TAG",
    dates: "Sept 1–30, 2026",
    opens: "2026-09-01",
    closes: "2026-09-30",
    why: "A Transfer Admission Guarantee for fall 2027 is filed in September.",
    action: "TAG requirements",
    url: UC_TAG,
    source: "University of California Admissions · Transfer Admission Guarantee (TAG)",
  },
  {
    id: "uc-apply-spring-2027",
    system: "UC",
    transfer: "Spring 2027",
    title: "Apply to UC",
    dates: "July 1–31, 2026",
    opens: "2026-07-01",
    closes: "2026-07-31",
    why: "UC's winter and spring 2027 application period.",
    action: "UC transfer dates",
    url: UC_APPLY,
    source: "University of California Admissions · Applying as a transfer student",
  },
  {
    id: "uc-apply-fall-2027",
    system: "UC",
    transfer: "Fall 2027",
    title: "Apply to UC",
    dates: "Oct 1–Nov 30, 2026",
    opens: "2026-10-01",
    closes: "2026-11-30",
    why: "UC's fall 2027 application period. Applications are due November 30.",
    action: "UC transfer dates",
    url: UC_APPLY,
    source: "University of California Admissions · Applying as a transfer student",
  },
  {
    id: "csu-apply-fall-2027",
    system: "CSU",
    transfer: "Fall 2027",
    title: "Apply on Cal State Apply",
    dates: "Oct 1–Nov 30, 2026",
    opens: "2026-10-01",
    closes: "2026-11-30",
    why: "The CSU's fall 2027 priority filing period. Submissions open October 1 and close November 30.",
    action: "CSU application dates",
    url: CSU_DATES,
    source: "The California State University · Application Dates & Deadlines",
  },
  {
    id: "fafsa-2027-28",
    system: "any",
    title: "File the FAFSA or California Dream Act Application",
    dates: "Oct 1, 2026–Mar 2, 2027",
    opens: "2026-10-01",
    closes: "2027-03-02",
    why: "March 2 is California's deadline for many state aid programs in 2027–28, including Cal Grants.",
    action: "2027–28 FAFSA form",
    url: FAFSA_FORM,
    source: "Federal Student Aid · 2027–28 FAFSA form (state deadlines)",
  },
];

/** From ASSIST's name for the university, as apps/api/app/services/ge/rules.py university_system. */
export function universitySystem(name: string | undefined): UniversitySystem | undefined {
  const n = (name ?? "").toLowerCase();
  if (n.startsWith("university of california")) return "UC";
  if (n.includes("state university") || n.includes("california polytechnic") || n.includes("cal poly"))
    return "CSU";
  return undefined;
}

/** "Fall 2027", Pacific "YYYY-MM-DD" today. The soonest-closing milestone still open or ahead, for this student. */
export function nextMilestone(
  university: string | undefined,
  transfer: string | undefined,
  today: string,
): Milestone | undefined {
  const system = universitySystem(university);
  const campus = /^University of California,\s*(.+)$/.exec(university ?? "")?.[1];
  return MILESTONES.filter(
    (m) =>
      (m.system === "any" || m.system === system) &&
      (!m.transfer || m.transfer === transfer) &&
      (!m.campuses || (!!campus && m.campuses.includes(campus))) &&
      m.closes >= today,
  ).sort((a, b) => a.closes.localeCompare(b.closes))[0];
}
