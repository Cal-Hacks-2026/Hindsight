// Catalog citations for the plan, read at build time from the same curated files the planner uses
// (data/requirements/*.json), so the cited page can't drift from the data. Only these keys are bundled.

type Group = { id: string; title: string; rule: "all" | "n_of" | "units"; units?: number | null; courses: string[] };

// import.meta.glob needs a literal pattern, hence the repetition.
const labels = import.meta.glob<string>("../../../../data/requirements/*.json", { eager: true, import: "major_label" });
const years = import.meta.glob<string>("../../../../data/requirements/*.json", { eager: true, import: "catalog_year" });
const urls = import.meta.glob<string>("../../../../data/requirements/*.json", { eager: true, import: "source_url" });
const groups = import.meta.glob<Group[]>("../../../../data/requirements/*.json", { eager: true, import: "groups" });
const campuses = import.meta.glob<string>("../../../../data/requirements/*.json", { eager: true, import: "campus" });

export type CatalogMajor = {
  campus: string;
  major_label: string;
  catalog_year: string;
  source_url: string;
  /** Unit requirements with no course list: the planner can't schedule them. */
  unscheduled: { title: string; units: number }[];
};

const CATALOG: CatalogMajor[] = Object.keys(labels).map((path) => ({
  campus: campuses[path]!,
  major_label: labels[path]!,
  catalog_year: years[path]!,
  source_url: urls[path]!,
  unscheduled: (groups[path] ?? [])
    .filter((g) => g.rule === "units" && g.courses.length === 0 && g.units)
    .map((g) => ({ title: g.title, units: g.units! })),
}));

/** A curated major at the student's campus; another campus's major with the same label doesn't count. */
export const catalogMajor = (label: string, campus: string) =>
  CATALOG.find((m) => m.major_label === label && m.campus === campus);

/** Whether we have the campus's degree requirements, so the plan goes past transfer. */
export const hasFullPlan = (campus: string) => CATALOG.some((m) => m.campus === campus);

/** "2025-26" → "2025–26" */
export const yearSpan = (year: string) => year.replace("-", "–");
