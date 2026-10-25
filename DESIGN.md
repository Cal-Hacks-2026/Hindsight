# Hindsight design language

## Identity

Name: **Hindsight**. Slogan: **Transfer Planner**.

Use the existing Janus engraving in `apps/web/public/brand/janus-ink.svg` as the main logo. Preserve the original artwork. Use the light variant when a dark background requires it. The two faces connect completed coursework with the student's next steps.

## Purpose

Help transfer students answer: what counts, what should I take next, and what could delay my transfer?

The plan is the starting point. Credits explain the evidence. Opportunities support campus participation. Ask Hindsight handles follow-up questions. Operational logs are not part of student navigation.

## Visual system

- Off-white paper, black typography, neutral surfaces, and subtle dotted-paper details.
- Bold, large sans-serif type. Page titles: 72–88px on desktop. Section headings: 28–32px. Body and inputs: 22–24px. Navigation and buttons: 20–22px. Supporting details: at least 18px.
- Adapt layout and title sizes for phones while keeping supporting text readable.
- Use short labels, direct recommendations, and generous space. Remove decorative kickers, repeated institution paths, current-term badges, blanket footer warnings, and explanatory text that duplicates the interface.
- Keep black line illustrations of books, stationery, graduation caps, and campus objects. They support hierarchy and empty states without competing with coursework.
- Make controls large enough for touch. Keep visible keyboard focus, semantic headings, and text labels alongside meaningful icons.

## Information hierarchy

1. Next proposed term: courses, units, prerequisites, and why each course is included.
2. Issues requiring action: unfinished sequences, uncertain equivalencies, or other documented blockers.
3. Progress: requirements met, in progress, partly complete, and still needed; estimated milestones with their limits.
4. Full course plan with start and transfer controls.
5. Sources and relevant details, reachable from the claims they support.

The credit view explains university requirements, confirmed prior coursework, and next actions. A missing published equivalency is not a rejected transfer-credit decision. Use readable course cards rather than dense tables for the student-facing credit review.

## Accuracy in the interface

Preserve citations, agreement-year differences, minimum-grade rules, confidence, sequence requirements, and catalog limitations. Targeted uncertainty belongs with the relevant decision. Do not substitute a repeated generic disclaimer for a clear explanation of what needs checking.

See [the product roadmap](docs/ROADMAP.md) for coverage and subsequent advising capabilities.
