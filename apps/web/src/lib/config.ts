export const APP_NAME = "Hindsight";
export const TAGLINE = "Transfer Planner";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const ASSIST_YEAR_2026_27 = 77;

/** ASSIST academic year id → "2026–27" (id = fall year − 1949). */
export const assistYear = (id: number) => `${id + 1949}–${String((id + 1950) % 100).padStart(2, "0")}`;
