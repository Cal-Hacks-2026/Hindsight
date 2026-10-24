import { Link, useLocation } from "react-router";
import type { MatchResult, Requirement } from "@hindsight/contracts";
import { loadSession } from "../lib/session";

const STATUS_LABEL: Record<Requirement["status"], string> = {
  satisfied: "Satisfied",
  partial: "Partial",
  missing: "Missing",
  at_university: "Take at university",
};

// Human copy for gotcha flags; unknown flags fall through as-is.
const FLAG_LABEL: Record<string, string> = {
  sequence_rule: "Entire sequence must be completed at the same college before transfer",
  min_grade_C: "Requires a C or better",
  no_current_articulation: "No current articulation — must be taken at the university",
  renumbered_course: "Matched via course renumbering",
};

export function Degree() {
  const location = useLocation();
  const matches: MatchResult[] | undefined =
    (location.state as { matches?: MatchResult[] } | null)?.matches ?? loadSession().matches;

  if (!matches?.length) {
    return (
      <section>
        <h1>Degree</h1>
        <p className="card">
          No results yet. <Link to="/onboarding">Upload your transcript</Link> to see what counts.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>Degree</h1>
      <p className="muted">What your confirmed courses satisfy, and what's left.</p>
      {matches.map((m) => (
        <MatchSection key={m.major_label} result={m} />
      ))}
      <h2>Semester plan</h2>
      <p className="card muted">Coming in Phase 1.</p>
    </section>
  );
}

function MatchSection({ result }: { result: MatchResult }) {
  const { summary } = result;
  return (
    <>
      <h2>{result.major_label}</h2>
      <div className="summary">
        <span className="chip satisfied">{summary.satisfied} satisfied</span>
        <span className="chip partial">{summary.partial} partial</span>
        <span className="chip missing">{summary.missing} missing</span>
        <span className="chip at_university">{summary.at_university} at university</span>
      </div>
      <ul className="requirements">
        {result.requirements.map((r) => (
          <RequirementCard key={r.id} req={r} />
        ))}
      </ul>
    </>
  );
}

function RequirementCard({ req }: { req: Requirement }) {
  return (
    <li className="card requirement">
      <div className="requirement-head">
        <div>
          <div className="requirement-title">{req.receiving_course}</div>
          <div className="muted">
            {req.group_title}
            {req.rule === "n_of" && req.n !== undefined && ` · choose ${req.n}`}
          </div>
        </div>
        <span className={`chip ${req.status}`}>{STATUS_LABEL[req.status]}</span>
      </div>

      {req.satisfied_by.length > 0 && <div>Counted from: {req.satisfied_by.join(", ")}</div>}

      {req.flags.map((f) => (
        <div key={f} className="flag">
          ⚠ {FLAG_LABEL[f] ?? f}
        </div>
      ))}

      <div className="row">
        <span className="chip neutral">Confidence: {req.confidence}</span>
        {req.confidence !== "high" && <span className="muted">Confirm with your advisor.</span>}
      </div>

      <div className="citation">
        Source:{" "}
        <a href={req.citation.url} target="_blank" rel="noreferrer">
          {req.citation.label}
        </a>
        {req.citation.ref && <span className="muted"> · {req.citation.ref}</span>}
      </div>
    </li>
  );
}
