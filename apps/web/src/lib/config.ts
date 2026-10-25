export const APP_NAME = "Hindsight";
export const TAGLINE = "Transfer Planner";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// ASSIST institution IDs (PROJECT.md §8.1): the onboarding defaults. Every other college and
// university comes from ASSIST's own lists (/assist/colleges, /assist/universities).
export const DE_ANZA_ID = 113;
export const SJSU_ID = 39;
export const ASSIST_YEAR_2026_27 = 77;

export const DE_ANZA_NAME = "De Anza College";
export const SJSU_NAME = "San José State University";

/** ASSIST academic year id → "2026–27" (id = fall year − 1949). */
export const assistYear = (id: number) => `${id + 1949}–${String((id + 1950) % 100).padStart(2, "0")}`;
