// What to expect at the student's university: short sections written only from the
// university's own pages, every item footnoted to them (GET /universities/{id}/guide).
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router";
import type {
  GuideSection,
  UniversityGuide,
  UniversityGuideResponse,
} from "@hindsight/contracts";
import { Masthead, Section } from "../components/Paper";
import { safeUrl } from "../components/Listing";
import { ApiError, api } from "../lib/api";
import { shortUniversity, universityName } from "../lib/format";
import { loadSession } from "../lib/session";
import "../styles/university.css";

type GuideState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; body: UniversityGuideResponse };

// Opportunities categories (RankedOpportunity.type), as the links name them.
const CATEGORY: Record<string, string> = {
  club: "Clubs",
  event: "Events",
  workshop: "Workshops",
  program: "Programs",
  position: "Open Positions",
  hackathon: "Hackathons",
};

function useGuide(universityId: number | undefined) {
  const [state, setState] = useState<GuideState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (universityId === undefined) return;
    let live = true;
    setState({ status: "loading" });
    api.universityGuide(universityId).then(
      (body) => live && setState({ status: "ready", body }),
      (error: unknown) => live && setState({ status: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [universityId, attempt]);
  return { state, retry: () => setAttempt((n) => n + 1) };
}

/** "2026-10-25" → "October 25, 2026", read as a calendar date (no time zone shift). */
function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(
    new Date(y, m - 1, d),
  );
}

export function University() {
  const { profile } = loadSession();
  const { state, retry } = useGuide(profile?.receiving_institution_id);
  const guide =
    state.status === "ready" && state.body.available
      ? state.body.guide
      : undefined;
  const name =
    guide?.university_name ??
    (state.status === "ready" ? state.body.university_name : undefined) ??
    (profile ? universityName(profile) : undefined);

  return (
    <>
      <Masthead
        sketch="cap"
        byline={
          guide
            ? `${guide.university_name} · Last updated ${formatDate(guide.last_updated)}`
            : name
        }
      >
        What to Expect
      </Masthead>
      {!profile ? (
        <Section label="University" title="Set Up Your Profile First" last>
          <div className="state">
            <p>
              Pick the university you're transferring to, and its guide shows up
              here.
            </p>
            <div className="actions">
              <Link className="button primary" to="/onboarding">
                Create your profile
              </Link>
            </div>
          </div>
        </Section>
      ) : state.status === "loading" ? (
        <Section label="University" title="Loading the Guide" last>
          <div className="state" role="status" aria-live="polite">
            <div className="loading-bar" aria-hidden="true" />
          </div>
        </Section>
      ) : state.status === "error" ? (
        <Section label="University" title="Couldn't Load the Guide" last>
          <div className="state" role="alert">
            <p>{errorDetail(state.error)}</p>
            <div className="actions">
              <button className="primary" onClick={retry}>
                Try again
              </button>
            </div>
          </div>
        </Section>
      ) : !guide ? (
        <Section
          label="University"
          title={`We don't have a guide for ${name ? shortUniversity(name) : "your university"} yet.`}
          last
        >
          <p className="lede-sub">
            Guides are written only from the university's own pages. SJSU's is
            the first.
          </p>
        </Section>
      ) : (
        <Guide guide={guide} opportunities={profile.campus !== "other"} />
      )}
    </>
  );
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429)
      return "Too many requests in a short time. Wait a minute, then try again.";
    return `The server returned an error (${error.status}${error.message ? `: ${error.message}` : ""}).`;
  }
  return "We couldn't reach the Hindsight server. Check your connection and try again.";
}

function Guide({
  guide,
  opportunities,
}: {
  guide: UniversityGuide;
  opportunities: boolean;
}) {
  const footnote = new Map(guide.sources.map((s, i) => [s.id, i + 1]));
  return (
    <>
      {guide.sections.map((section) => (
        <GuideSectionView
          key={section.id}
          section={section}
          footnote={footnote}
          opportunities={opportunities}
        />
      ))}
      <Section id="sources" label="Sources" title="Sources" last>
        <div className="source-list">
          {guide.sources.map((source, i) => {
            const url = safeUrl(source.url);
            return (
              <p key={source.id} id={`source-${i + 1}`}>
                <strong>{i + 1}.</strong>{" "}
                {url ? (
                  <a href={url.href} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                ) : (
                  source.title
                )}
                , {source.publisher}.
                {source.retrieved_on !== guide.last_updated &&
                  ` Read ${formatDate(source.retrieved_on)}.`}
              </p>
            );
          })}
        </div>
      </Section>
    </>
  );
}

function GuideSectionView({
  section,
  footnote,
  opportunities,
}: {
  section: GuideSection;
  footnote: Map<string, number>;
  opportunities: boolean;
}) {
  const categories = opportunities
    ? (section.opportunity_types ?? []).filter((t) => CATEGORY[t])
    : [];
  return (
    <Section
      id={`guide-${section.id}`}
      label={section.title}
      title={section.title}
      notes={
        categories.length > 0 && (
          <p className="guide-links">
            <strong>In Opportunities:</strong>{" "}
            {categories.map((t, i) => (
              <Fragment key={t}>
                {i > 0 && " · "}
                <Link to={`/radar?type=${encodeURIComponent(t)}`}>
                  {CATEGORY[t]}
                </Link>
              </Fragment>
            ))}
          </p>
        )
      }
    >
      <ul className="guide-items">
        {section.items.map((item, i) => (
          <li key={i}>
            {item.text}
            <Refs
              ns={item.source_ids.flatMap((id) => footnote.get(id) ?? [])}
            />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Refs({ ns }: { ns: number[] }) {
  const sorted = [...new Set(ns)].sort((a, b) => a - b);
  if (!sorted.length) return null;
  return (
    <sup className="ref">
      {sorted.map((n, i) => (
        <Fragment key={n}>
          {i > 0 && ","}
          <a href={`#source-${n}`} aria-label={`Source ${n}`}>
            {n}
          </a>
        </Fragment>
      ))}
    </sup>
  );
}
