export const APP_NAME = "Hindsight";
export const TAGLINE = "Transfer Planner";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// SJSU's ASSIST id (PROJECT.md §8.1): the one university with a full plan, so it keeps its own
// profile campus. It's not a default; every college and university is picked from ASSIST's lists.
export const SJSU_ID = 39;
export const ASSIST_YEAR_2026_27 = 77;

export const SJSU_NAME = "San José State University";

/** ASSIST academic year id → "2026–27" (id = fall year − 1949). */
export const assistYear = (id: number) => `${id + 1949}–${String((id + 1950) % 100).padStart(2, "0")}`;
