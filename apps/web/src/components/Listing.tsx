// One Radar listing as a compact card: title, when and where, one reason line, its source.
import type { RankedOpportunity } from "@hindsight/contracts";
import { closeAt, formatDay, formatWhen, timeLeft } from "../lib/time";

export const TYPE_LABEL: Record<string, string> = {
  hackathon: "Hackathon",
  program: "Program",
  position: "Open position",
  workshop: "Workshop",
  club: "Club",
  event: "Event",
};

export const typeLabel = (type: string) => TYPE_LABEL[type] ?? type;

const MODALITY_LABEL: Record<string, string> = {
  in_person: "In person",
  online: "Online",
  hybrid: "Hybrid",
};

const checkedFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/** "Checked Oct 25, 2026" for a program's YYYY-MM-DD last_checked. */
function checkedOn(day: string): string | null {
  const at = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? null : `Checked ${checkedFmt.format(at)}`;
}

// Scraped URLs are untrusted: only link out to http(s).
export function safeUrl(url: string): URL | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed
      : undefined;
  } catch {
    return undefined;
  }
}

export const hostOf = (url: URL) => url.hostname.replace(/^www\./, "");

/** Droid alerted on this listing (RankedOpportunity.notified). */
export function NewLabel() {
  return (
    <span className="new-label" title="Found on a recent campus scan">
      New
    </span>
  );
}

/** One opportunity as a compact card: title, when and where, one reason line, the source. */
export function Listing({
  item,
  now,
  kind,
  fit,
  campus,
}: {
  item: RankedOpportunity;
  now: number;
  /** The listing's subcategory label ("Career Fairs"); the item type otherwise. */
  kind?: string;
  /** Why it fits the student's week: "Free Tuesday 2–5 PM". */
  fit?: string;
  /** Whose listing it is: "At <university>, your target school" (lib/campuses campusLabel). */
  campus?: string;
}) {
  const link = safeUrl(item.url);
  const target = closeAt(item, now);
  const isHackathon = item.type === "hackathon";
  const beforeStart = isHackathon && target === item.starts_at;
  const raw = target ? timeLeft(target, now) : null;
  const left =
    raw && raw.urgency !== "past"
      ? `${raw.value} ${(beforeStart ? raw.unit.replace(/ left$/, " to start") : raw.unit).toLowerCase()}`
      : raw
        ? "Closed"
        : null;
  const starts = item.starts_at ? formatWhen(item.starts_at) : null;
  const due = item.deadline ? formatWhen(item.deadline) : null;
  // A hackathon's scraped end date is when it wraps up, not a registration deadline.
  const from = item.starts_at ? formatDay(item.starts_at) : null;
  const to = item.deadline ? formatDay(item.deadline) : null;
  const recurring = item.type === "program" && item.window;
  const when = isHackathon
    ? from && to && from !== to
      ? `Runs ${from} – ${to}`
      : (from ?? to ?? "")
    : recurring
      ? item.window!
      : [starts && `Starts ${starts}`, due && `Deadline ${due}`]
          .filter(Boolean)
          .join(" · ");
  const where = [
    campus,
    item.modality && MODALITY_LABEL[item.modality],
    item.location,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="opp-card">
      <h3 className="opp-title">
        {link ? (
          <a href={link.href} target="_blank" rel="noreferrer">
            {item.title}
          </a>
        ) : (
          item.title
        )}
        {item.notified && <NewLabel />}
      </h3>
      {fit && <p className="entry-fit">{fit}</p>}
      {(when || left) && (
        <p className="opp-when">
          {when}
          {left && (
            <span className={`opp-left ${raw!.urgency}`}>
              {when ? " · " : ""}
              {left}
            </span>
          )}
        </p>
      )}
      {where && <p className="opp-where">{where}</p>}
      {item.reason && (
        <p className="opp-reason" title={item.reason}>
          {item.reason}
        </p>
      )}
      <p className="opp-foot">
        {[kind ?? typeLabel(item.type), item.org].filter(Boolean).join(" · ")}
        {recurring && item.last_checked && ` · ${checkedOn(item.last_checked)}`}
        {link && (
          <>
            {" · "}
            <a
              href={link.href}
              target="_blank"
              rel="noreferrer"
              aria-label={`Source: ${hostOf(link)}`}
            >
              {hostOf(link)} ↗
            </a>
          </>
        )}
      </p>
    </li>
  );
}
