# DESIGN.md — Hindsight design language

> Read this before touching any UI. It defines how Hindsight looks and why.
> Companion docs: `PROJECT.md` (what we build), `DECISIONS.md` (why we decided).

---

## 1. The vibe in one line

**"An academic institution that publishes research, designed by a Swiss modernist."**

Old-world authority, modern restraint, and an interface that reads like a well-typeset paper. Hindsight gives students **high-stakes advice about their degree**, so the design must earn trust: calm, rigorous, sourced, permanent.

It fuses three layers plus one motif:

| Layer | What it brings | Reference |
|---|---|---|
| **Heritage institution** | Authority, permanence: "this advice can be trusted" | Engraved circular seals (lion + crown + keys, chariot); the Yale serif headline |
| **Scientific paper** | Rigor: everything numbered, sourced, captioned | Yale deck's numbered table of contents and "THE PROBLEM / THE GOAL" rows on hairline rules |
| **Swiss minimalism** | Clarity and calm; good UX through restraint | Brand.AI's clean grotesk; tiny Helvetica corner labels; time & space hairlines and whitespace |
| **Motif: the bookshelf** | The library, the archive, accumulated knowledge | Book spines in the Yale deck, Artspace, and time & space |

---

## 2. Lessons from each reference

1. **Yale redesign concept (Tetiana Prokhoda):** huge, tightly stacked serif headline in black with **one word in italic blue**. Tiny uppercase sans labels pinned to the corners. Grainy paper-gray background. Thin full-width rules between sections. Section numbers in a **light gray** that recedes. → *One accent color, used once per screen, in italic.*
2. **The seals:** monochrome, engraved/woodcut line work, circular, symbolic. → *The logo is a seal, not a startup glyph.*
3. **Artspace "Upcoming Releases":** high-contrast serif display above a shelf of colorful spines. → *Color lives inside objects (spines, chips); the page stays neutral.*
4. **time & space Book Corner:** hairline under the title, small sans paragraph, browsable shelf. → *The shelf can be the navigation; browsing feels physical.*
5. **Brand.AI "A living OS":** giant grotesk, black for the statement and warm gray for the rest; soft neutral floating cards; pill tags. → *Hierarchy through value (black vs. gray), not only size; quiet components.*

---

## 3. Identity

### Logo: the Janus seal
A circular, engraved-style emblem, black on paper. The symbol is **Janus**, the Roman god with two faces: one looking back, one looking forward. That is *hindsight + foresight*: the transcript (past) and the plan (future).

Around the ring, the Latin motto ***Respice · Prospice*** ("look back, look forward").

**Rule:** the seal must be **original**. Evoke Stanford/Harvard/Oxford; never copy their marks.

### Wordmark
`HINDSIGHT` in Helvetica bold, uppercase, slight tracking (0.08em), with the subline *Plan Your Four-Year Journey* beneath it in small gray type. The logo and wordmark appear once, in the header; no page repeats them.

---

## 4. Typography

**One family for the whole site:** `"Helvetica Neue", Helvetica, Arial, sans-serif` (the `--font` token). No web fonts, no second family. Hierarchy comes from **weight and size**, and from **value** (ink vs. warm gray).

| Role | Style | Usage |
|---|---|---|
| **Page title** | Bold, 28–40px, tight leading | One per page, plain words in Title Case: "Your Degree", "Opportunities". Kept compact: header + title stay within ~20% of the first screen |
| **Section titles** | Bold, 22–26px | Title Case: "Credits Toward Your Requirements" |
| **Labels** | Bold, 13–14px, sentence or Title Case as written; never uppercase-tracked | Section labels, field labels, table heads |
| **Body** | Regular, 15px base; 19–22px for a lead sentence | Everything you read; sentence case |
| **Large numerals** | Light (300), warm gray | Section numbers, listing ranks |
| **Course codes** | Tabular figures | `MATH 1A`, `ECON 101` scan like data |

**Copy rules.** Title Case for headings, nav items, buttons and section titles; sentence case for body sentences. No eyebrow or kicker lines above titles, no copy that describes the page's own structure ("Methods", "How it was made", "Prepared for…"), no taglines inside pages. Where a section needs a title, name it plainly.

---

## 5. Color

| Token | Use |
|---|---|
| **Paper** | Grainy off-white background |
| **Ink** | Near-black text and rules |
| **Gray** | Secondary text, receding section numerals |
| **Hairline** | Thin full-width rules (ink at low opacity) |
| **Accent: institutional blue** | The ONE accent. Max once per screen: link hover, the active state, or a single callout rule |
| **Status (muted)** | Satisfied = muted green · Partial = muted ochre · Missing = muted red · At-university-only = slate blue |

Color inside objects (book spines by department, chips) is allowed; the page itself stays neutral.

---

## 6. Scientific-paper UX patterns

This is what makes the style functional, not decorative. **"High-stakes advice, cited" becomes visible design.**

| Paper convention | Hindsight feature |
|---|---|
| **Abstract** | Top of Degree: "34 units remain. 2 requirements need attention. Earliest finish: Spring 2029." |
| **Numbered sections** | §1 Credits · §2 Remaining · §3 Plan · §4 Opportunities, with large light-gray numerals |
| **Footnote citations** | Every claim carries a superscript `¹`; sources sit in the margin as **sidenotes** (ASSIST row, catalog page, opportunity URL) |
| **Figures with captions** | "Fig. 1: Your path to graduation" |
| **Tables with hairline rules** | Course lists in classic academic style: no boxes, thin rules only |

---

## 7. Signature visual: the bookshelf

**Your degree is a shelf.**
- Each **completed** course is a **spine already on the shelf**.
- **Remaining** courses are **outlined empty slots**.
- Each **semester** of the plan is a **shelf row**.
- Spines are **colored by department** (MATH, ECON, DATA, ENGL).
- Radar opportunities can also render as spines.

A judge understands "I have most of my books; here's what's missing" instantly.

---

## 8. Sketch: Degree screen

```
HINDSIGHT · SJSU                                   DATA SCIENCE + ECONOMICS · FALL 2026
────────────────────────────────────────────────────────────────────────────────────────
Your Degree                                                       ← compact bold page title

ABSTRACT  34 units remain. Two requirements need attention.¹ Earliest finish: Spring 2029.²
────────────────────────────────────────────────────────────────────────────────────────
01   CREDITS                                                        ¹ ASSIST, De Anza → SJSU,
     ▌▌▌▌▌ ▌▌▌ ▌▌▌▌  ┆ ┆ ┆                                           2023–24, row 14
     (shelved spines = done · dashed slots = missing)               ² SJSU Catalog 2025–26 p. 412

02   PLAN                                         Fig. 1: Your path to graduation
     FALL 27   ▌▌▌▌
     SPR 28    ▌▌▌ ┆
```

---

## 9. References

- **Tufte CSS** (edwardtufte.github.io/tufte-css): sidenote citations, scientific-paper web layout
- **Distill.pub**: research articles as interactive web pages
- **Stripe Press** (press.stripe.com): books as UI objects; serif + sans; institutional calm
- **Works in Progress** magazine: modern editorial serif, scholarly and clean
- **Swiss Style** (Josef Müller-Brockmann, Massimo Vignelli): grid, Helvetica, hairline discipline

---

## 10. Rules for anyone building UI (including Claude Code)

1. One accent color, used at most once per screen.
2. One family (Helvetica) everywhere; hierarchy through weight and size, not a second font.
3. No boxes where a hairline rule will do.
4. Every academic claim shows its citation.
5. Generous whitespace; let it breathe.
6. The seal and wordmark are original, never borrowed university marks.
