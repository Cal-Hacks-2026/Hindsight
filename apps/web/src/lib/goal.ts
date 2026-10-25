// Reads a target graduation term out of the free-text goals field ("Graduate by Spring 2028").
const SEASON_ORDER: Record<string, number> = { winter: 0, spring: 1, summer: 2, fall: 3 };
const TERM_RE = /\b(winter|spring|summer|fall)\s+(?:of\s+)?'?(20)?(\d{2})\b/i;
const YEAR_RE = /\b(?:by|in|before|until)\s+(20\d{2})\b/i;

export type GoalTerm = { label: string; index: number };

export const termIndex = (term: string): number | undefined => {
  const m = TERM_RE.exec(term);
  if (!m) return undefined;
  return Number(`20${m[3]}`) * 4 + SEASON_ORDER[m[1]!.toLowerCase()]!;
};

export function parseGoalTerm(goals: string): GoalTerm | undefined {
  const t = TERM_RE.exec(goals);
  if (t) {
    const season = t[1]!.charAt(0).toUpperCase() + t[1]!.slice(1).toLowerCase();
    const year = Number(`20${t[3]}`);
    return { label: `${season} ${year}`, index: year * 4 + SEASON_ORDER[season.toLowerCase()]! };
  }
  const y = YEAR_RE.exec(goals);
  if (y) return { label: y[1]!, index: Number(y[1]) * 4 + SEASON_ORDER.fall! };
  return undefined;
}
