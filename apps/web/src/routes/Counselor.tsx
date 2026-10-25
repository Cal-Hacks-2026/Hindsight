// Counselor: ask about your plan; every answer shows its sources (DESIGN.md §6).
// The API returns plain text with [n] markers, "- " bullets, and an optional
// "Confirm with your advisor…" tail (apps/api/app/services/counselor.py); we lay that out here.
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type Ref,
} from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { ChatMessage, Citation } from "@hindsight/contracts";
import { Masthead } from "../components/Paper";
import { Icon } from "../components/Icons";
import { api, ApiError } from "../lib/api";
import { loadSession } from "../lib/session";
import { useNow } from "../lib/time";
import "../styles/counselor.css";

type Exchange = {
  question: string;
  state:
    | { status: "pending"; startedAt: number }
    | { status: "error"; error: unknown }
    | {
        status: "done";
        reply: string;
        citations: Citation[];
      };
};

// One question each about the plan, GE, the class schedule and the University guide.
const FIRST_CHIPS = [
  "What should I take next term?",
  "Which GE areas do I still need?",
  "When am I free on Thursday?",
  "What's orientation like?",
];
// No summer-term chip: the planner schedules Fall and Spring only (AUDIT I-12).
const NEXT_CHIPS = [
  "What do I still need for my major?",
  "Which GE areas do I still need?",
  "When am I free on Thursday?",
  "What's orientation like?",
  "Which requirements should I check with my advisor?",
];
const CHIPS_SHOWN = 4;

export function Counselor() {
  const { profile } = loadSession();
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const latest = useRef<HTMLElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const handedOff = useRef(false);

  const busy = exchanges.at(-1)?.state.status === "pending";

  useEffect(() => {
    latest.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [exchanges.length]);

  async function ask(question: string, before: Exchange[]) {
    if (!profile || !question.trim()) return;
    const history: ChatMessage[] = before.flatMap((e) =>
      e.state.status === "done"
        ? [
            { role: "user", content: e.question },
            { role: "assistant", content: e.state.reply },
          ]
        : [],
    );
    const pending: Exchange = {
      question: question.trim(),
      state: { status: "pending", startedAt: Date.now() },
    };
    setExchanges([...before, pending]);
    setDraft("");
    let state: Exchange["state"];
    try {
      const res = await api.counselor(profile.id, {
        message: pending.question,
        history,
      });
      state = { status: "done", reply: res.reply, citations: res.citations };
    } catch (error) {
      state = { status: "error", error };
    }
    setExchanges([...before, { ...pending, state }]);
  }

  // A question typed on Degree arrives as router state and ?q= (a shared link has only ?q=).
  // Ask it once, then drop it from the URL and history so a reload doesn't ask again.
  useEffect(() => {
    if (handedOff.current) return;
    handedOff.current = true;
    const question =
      (location.state as { question?: string } | null)?.question ??
      params.get("q");
    if (!question?.trim()) return;
    navigate(location.pathname, { replace: true });
    void ask(question, []);
  }, []);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!busy) void ask(draft, exchanges);
  }

  const asked = new Set(exchanges.map((e) => e.question));
  const chips = (exchanges.length ? NEXT_CHIPS : FIRST_CHIPS)
    .filter((c) => !asked.has(c))
    .slice(0, CHIPS_SHOWN);

  return (
    <div className="cs">
      <Masthead sketch="pencil">Ask Hindsight</Masthead>

      {!profile ? (
        <section className="cs-row">
          <div className="cs-label cs-row-label">
            <Icon name="chat" size={18} />
            Get started
          </div>
          <div className="cs-main">
            <p className="cs-lead">
              Your transcript. Your plan. Your questions.
            </p>
            <p>
              <Link to="/onboarding">Set up your profile</Link> to get answers
              about your degree.
            </p>
          </div>
          <div className="cs-margin" />
        </section>
      ) : (
        <>
          {exchanges.map((ex, i) => (
            <ExchangeView
              key={i}
              ref={i === exchanges.length - 1 ? latest : undefined}
              index={i}
              exchange={ex}
              onRetry={
                i === exchanges.length - 1 && ex.state.status === "error"
                  ? () => void ask(ex.question, exchanges.slice(0, i))
                  : undefined
              }
            />
          ))}

          <section className="cs-row cs-ask">
            <div className="cs-label cs-row-label">
              {exchanges.length ? "Ask next" : "Ask"}
            </div>
            <form className="cs-main cs-form" onSubmit={onSubmit}>
              <label htmlFor="cs-question" className="cs-sr">
                Your question
              </label>
              <div className="cs-inputs">
                <input
                  id="cs-question"
                  type="text"
                  value={draft}
                  maxLength={2000}
                  placeholder={
                    exchanges.length
                      ? "Ask a follow-up question"
                      : "What would you like to figure out?"
                  }
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={busy}
                />
                <button
                  type="submit"
                  className="cs-btn cs-btn-solid"
                  disabled={busy || !draft.trim()}
                >
                  <Icon name="arrow" size={20} />
                  <span className="sr-only">Send question</span>
                </button>
              </div>
              {chips.length > 0 && (
                <div className="cs-chips">
                  {chips.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      className="cs-chip"
                      disabled={busy}
                      onClick={() => void ask(chip, exchanges)}
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              )}
            </form>
            <div className="cs-margin" />
          </section>
        </>
      )}
    </div>
  );
}

function ExchangeView({
  exchange,
  index,
  onRetry,
  ref,
}: {
  exchange: Exchange;
  index: number;
  onRetry?: () => void;
  ref?: Ref<HTMLElement>;
}) {
  const { question, state } = exchange;
  return (
    <article
      ref={ref}
      className="cs-exchange"
      aria-label={`Question ${index + 1}`}
    >
      <section className="cs-row">
        <div className="cs-label cs-row-label">You asked</div>
        <p className="cs-main cs-question">“{question}”</p>
        <div className="cs-margin" />
      </section>

      <section className="cs-row">
        <div className="cs-label cs-row-label">Answer</div>
        {state.status === "pending" ? (
          <Pending startedAt={state.startedAt} />
        ) : state.status === "error" ? (
          <div className="cs-main" role="alert">
            <p className="cs-lead">{errorTitle(state.error)}</p>
            <p className="cs-muted">{errorDetail(state.error)}</p>
            {onRetry && (
              <button type="button" className="cs-btn" onClick={onRetry}>
                Try Again
              </button>
            )}
          </div>
        ) : (
          <Answer
            reply={state.reply}
            citations={state.citations}
            id={`q${index + 1}`}
          />
        )}
        {state.status !== "done" && <div className="cs-margin" />}
      </section>
    </article>
  );
}

// A counselor answer can take a while: Claude may call the planner a few times.
function Pending({ startedAt }: { startedAt: number }) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const message =
    seconds < 5
      ? "Reading your transcript and plan…"
      : seconds < 20
        ? "Running the matcher and planner for your question…"
        : "Still working. Questions that compare plans take longer.";
  return (
    <div className="cs-main cs-pending" role="status" aria-live="polite">
      <p className="cs-lead">{message}</p>
      <span className="cs-num" aria-hidden="true">
        {seconds}s
      </span>
    </div>
  );
}

function Answer({
  reply,
  citations,
  id,
}: {
  reply: string;
  citations: Citation[];
  id: string;
}) {
  const { body, advisor } = splitAdvisor(reply);
  const blocks = toBlocks(body);
  const cite = (text: string) => withCitations(text, citations.length, id);
  let lead = true;

  return (
    <>
      <div className="cs-main">
        {blocks.map((block, i) => {
          if (block.kind === "list") {
            return (
              <ol key={i} className="cs-list">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <span className="cs-numeral" aria-hidden="true">
                      {roman(j + 1)}.
                    </span>
                    <span>{cite(item)}</span>
                  </li>
                ))}
              </ol>
            );
          }
          const isLead = lead;
          lead = false;
          return (
            <p key={i} className={isLead ? "cs-lead" : "cs-para"}>
              {cite(block.text)}
            </p>
          );
        })}
        {advisor && <AdvisorBlock question={advisor} cite={cite} />}
      </div>

      <aside className="cs-margin cs-sources" aria-label="Sources">
        {citations.length === 0 ? (
          <>
            <div className="cs-label cs-sources-head">Sources</div>
            <p className="cs-note">
              This answer comes from your own profile and transcript.
            </p>
          </>
        ) : (
          // Closed under "Sources (N)"; a citation in the answer opens it (Layout).
          <details className="sources-details">
            <summary className="cs-label cs-sources-head">
              Sources ({citations.length})
              <Icon name="chevron" size={16} />
            </summary>
            <ol>
              {citations.map((c, i) => (
                <li key={i} id={`${id}-cite-${i + 1}`}>
                  <strong>{i + 1}</strong>
                  <span>
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noreferrer">
                        {c.label}
                      </a>
                    ) : (
                      c.label
                    )}
                    {c.ref && <span className="cs-ref"> · {c.ref}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        )}
        {citations.some((c) => c.source === "catalog") && (
          <p className="cs-note">
            Catalog data is from 2025–26 and assumes every course is offered in
            Fall and Spring.
          </p>
        )}
      </aside>
    </>
  );
}

function AdvisorBlock({
  question,
  cite,
}: {
  question: string;
  cite: (text: string) => ReactNode[];
}) {
  const [copied, setCopied] = useState(false);
  const plain = stripMarkers(question);
  const mailto = `mailto:?${new URLSearchParams({
    subject: "Question about my degree plan",
    body: plain,
  })
    .toString()
    .replace(/\+/g, "%20")}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(plain);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard blocked: the question is on screen to select by hand
    }
  }

  return (
    <div className="cs-advisor">
      <div className="cs-label">Confirm with your advisor</div>
      <p className="cs-advisor-q">“{cite(question)}”</p>
      <div className="cs-actions">
        <a className="cs-btn cs-btn-solid" href={mailto}>
          Email My Advisor
        </a>
        <button type="button" className="cs-btn" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy Question"}
        </button>
      </div>
    </div>
  );
}

// ---- reply parsing ----

const ADVISOR =
  /\n*Confirm with your advisor\.[^\n]*\n\s*[“"]([\s\S]+?)[”"]\s*$/;
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;
const MARKERS = /(?:\[\d+\])+/g;

function splitAdvisor(reply: string): { body: string; advisor?: string } {
  const m = ADVISOR.exec(reply);
  return m
    ? { body: reply.slice(0, m.index), advisor: m[1].trim() }
    : { body: reply };
}

type Block = { kind: "para"; text: string } | { kind: "list"; items: string[] };

function toBlocks(body: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of body.split("\n")) {
    const line = raw.trim();
    const last = blocks.at(-1);
    if (!line) {
      if (last?.kind === "para") blocks.push({ kind: "para", text: "" });
      continue;
    }
    if (BULLET.test(line)) {
      const item = line.replace(BULLET, "");
      if (last?.kind === "list") last.items.push(item);
      else blocks.push({ kind: "list", items: [item] });
    } else if (last?.kind === "para") {
      last.text = last.text ? `${last.text} ${line}` : line;
    } else {
      blocks.push({ kind: "para", text: line });
    }
  }
  return blocks.filter((b) => b.kind === "list" || b.text);
}

/**
 * "…ends Spring 2029.[1][2]" → text with a superscript "1,2" linking to the margin. The last word
 * and its superscript stay together so a citation never wraps onto its own line.
 */
function withCitations(text: string, count: number, id: string): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  for (const m of text.matchAll(MARKERS)) {
    const before = text.slice(at, m.index).replace(/\s+$/, "");
    const nums = [
      ...new Set(
        [...m[0].matchAll(/\d+/g)]
          .map((n) => Number(n[0]))
          .filter((n) => n >= 1 && n <= count),
      ),
    ];
    if (nums.length) {
      const word = before.search(/\S+$/);
      const tail = word < 0 ? "" : before.slice(word);
      out.push(
        word < 0 ? before : before.slice(0, word),
        <span key={m.index} className="cs-cited">
          {tail}
          <sup className="cs-cite">
            {nums.map((n, i) => (
              <Fragment key={n}>
                {i > 0 && ","}
                <a href={`#${id}-cite-${n}`} aria-label={`Source ${n}`}>
                  {n}
                </a>
              </Fragment>
            ))}
          </sup>
        </span>,
      );
    } else {
      out.push(before);
    }
    at = m.index + m[0].length;
  }
  out.push(text.slice(at));
  return out;
}

function stripMarkers(text: string): string {
  return text.replace(MARKERS, "").replace(/\s+([.,;:?])/g, "$1");
}

function roman(n: number): string {
  const table: [number, string][] = [
    [10, "x"],
    [9, "ix"],
    [5, "v"],
    [4, "iv"],
    [1, "i"],
  ];
  let out = "";
  for (const [value, numeral] of table) {
    while (n >= value) {
      out += numeral;
      n -= value;
    }
  }
  return out;
}

function errorTitle(error: unknown): string {
  if (error instanceof ApiError && error.status === 404)
    return "We couldn't find your profile.";
  return "The counselor couldn't answer that.";
}

function errorDetail(error: unknown): string {
  if (!(error instanceof ApiError))
    return "We couldn't reach the Hindsight server. Check your connection and try again.";
  if (error.status === 404)
    return "It may have been reset on the server. Set it up again from Onboarding.";
  if (error.status === 429)
    return "Too many questions in a short time. Wait a minute, then try again.";
  return (
    error.message || "Something went wrong on our side. Try again in a moment."
  );
}
