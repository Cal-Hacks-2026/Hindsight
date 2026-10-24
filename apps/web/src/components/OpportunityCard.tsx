import type { RankedOpportunity } from "@hindsight/contracts";
import { countdown, formatWhen } from "../lib/time";

const TYPE_LABEL: Record<string, string> = {
  hackathon: "Hackathon",
  program: "Program",
  position: "Open position",
  workshop: "Workshop",
  club: "Club",
  event: "Event",
};

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function TypeBadge({ type }: { type: string }) {
  const known = type in TYPE_LABEL;
  return <span className={`chip type ${known ? `type-${type}` : ""}`}>{known ? TYPE_LABEL[type] : type}</span>;
}

export function DeadlineCountdown({ deadline, now }: { deadline: string; now: number }) {
  const left = countdown(deadline, now);
  const when = formatWhen(deadline);
  if (!left || !when) return null;
  return (
    <span className={`deadline ${left.urgency}`}>
      <span className="deadline-left">{left.label}</span>
      <span className="muted"> · due {when}</span>
    </span>
  );
}

export function OpportunityCard({
  item,
  now,
  rank,
  as: Tag = "li",
}: {
  item: RankedOpportunity;
  now: number;
  rank?: number;
  as?: "li" | "article";
}) {
  const starts = item.starts_at ? formatWhen(item.starts_at) : null;
  return (
    <Tag className="card opportunity">
      <div className="opportunity-head">
        {rank !== undefined && (
          <span className="rank" aria-label={`Rank ${rank}`}>
            {rank}
          </span>
        )}
        <div className="opportunity-title-block">
          <a className="opportunity-title" href={item.url} target="_blank" rel="noreferrer">
            {item.title}
          </a>
          {item.org && <div className="muted">{item.org}</div>}
        </div>
        <TypeBadge type={item.type} />
      </div>

      {item.reason && (
        <div className="reason">
          <span className="reason-label">Why this fits you</span>
          <p>{item.reason}</p>
        </div>
      )}

      <div className="opportunity-meta">
        {item.deadline && <DeadlineCountdown deadline={item.deadline} now={now} />}
        {starts && <span className="muted">Starts {starts}</span>}
        <a className="source" href={item.url} target="_blank" rel="noreferrer">
          Source: {hostname(item.url)} ↗
        </a>
      </div>
    </Tag>
  );
}
