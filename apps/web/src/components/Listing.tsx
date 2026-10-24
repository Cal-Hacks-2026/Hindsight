// One Radar listing as a ruled entry: a big numeral (time left, or rank), the listing, its source.
import type { RankedOpportunity } from "@hindsight/contracts";
import { formatWhen, timeLeft } from "../lib/time";

export const TYPE_LABEL: Record<string, string> = {
  hackathon: "Hackathon",
  program: "Program",
  position: "Open position",
  workshop: "Workshop",
  club: "Club",
  event: "Event",
};

export const typeLabel = (type: string) => TYPE_LABEL[type] ?? type;

// Scraped URLs are untrusted: only link out to http(s).
export function safeUrl(url: string): URL | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed : undefined;
  } catch {
    return undefined;
  }
}

export const hostOf = (url: URL) => url.hostname.replace(/^www\./, "");

export function Listing({
  item,
  now,
  rank,
}: {
  item: RankedOpportunity;
  now: number;
  /** Lead with the rank numeral instead of the time left. */
  rank?: number;
}) {
  const link = safeUrl(item.url);
  const left = item.deadline ? timeLeft(item.deadline, now) : null;
  const due = item.deadline ? formatWhen(item.deadline) : null;
  const starts = item.starts_at ? formatWhen(item.starts_at) : null;
  const when = [starts && `Starts ${starts}`, due && `Due ${due}`].filter(Boolean).join(" · ");
  const meta = [typeLabel(item.type), item.org, link && hostOf(link)].filter(Boolean).join(" · ");

  return (
    <li className="entry">
      <div className="entry-lead">
        {rank !== undefined ? (
          <>
            <div className="entry-big rank" aria-label={`Rank ${rank}`}>
              {String(rank).padStart(2, "0")}
            </div>
            {left && (
              <div className={`label ${left.urgency}`}>
                {left.urgency === "past" ? "Closed" : `${left.value} ${left.unit.toLowerCase()}`}
              </div>
            )}
          </>
        ) : left ? (
          <>
            <div className="entry-big">{left.urgency === "past" ? "—" : left.value}</div>
            <div className={`label ${left.urgency}`}>{left.unit}</div>
          </>
        ) : (
          <>
            <div className="entry-big">—</div>
            <div className="label later">No deadline</div>
          </>
        )}
      </div>
      <div className="entry-body">
        <div className="meta">{meta}</div>
        <h3>{link ? <a href={link.href} target="_blank" rel="noreferrer">{item.title}</a> : item.title}</h3>
        {item.reason && <p className="entry-reason">{item.reason}</p>}
        {when && <p className="entry-when">{when}</p>}
      </div>
      {link && (
        <a className="entry-source" href={link.href} target="_blank" rel="noreferrer" aria-label={`Source: ${hostOf(link)}`}>
          Source ↗
        </a>
      )}
    </li>
  );
}
