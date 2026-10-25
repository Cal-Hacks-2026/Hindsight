# Hindsight — Transfer Planner

The goal is to prevent wasted courses, missed requirements, and lost semesters for students transferring from community colleges to universities.

## Product decisions

- Name: Hindsight. Slogan: Transfer Planner.
- The original Janus engraving remains the main logo.
- The student experience centers on three questions: what counts, what to take next, and what could delay transfer.
- Navigation: My plan, My credits, Opportunities, Ask Hindsight.
- Lead with the next proposed term, coursework, units, and the requirement each course addresses.
- Distinguish meeting a major requirement from receiving general transfer credit. Never treat a missing published equivalency as a denial.
- Keep sources next to decisions. Explain uncertainty where it changes a student's next action.
- Background scanning and scraper maintenance stay out of student navigation.
- Schools appear where they explain a plan or an equivalency, rather than as repeated page decoration.

## Current frontend scope

Use existing confirmed transcript rows, deterministic match results, plans, and opportunity data. Separate planning and credit review into dedicated screens. Keep prerequisites, course alternatives, agreement years, confidence, exceptions, citations, term controls, and follow-up questions accessible. Do not claim that the major-preparation plan is a complete transfer-admission or graduation audit.

The first supported onboarding pathway remains De Anza to SJSU. A consistent nationwide interface does not establish nationwide data coverage. Any community college and university with ASSIST agreements is selectable; credit matching and community-college terms come from ASSIST. Only schools with verified degree requirements (SJSU today) get a Full Plan, and the others say so plainly.

## Subsequent work

1. Add verified institution pairs, multiple previous colleges, and catalog-year selection. Normalize institutional rules and quarter/semester calendars behind the same student workflow.
2. Compare destinations by remaining requirements and estimated completion time, preserving the limits of each comparison.
3. Add general education, admission prerequisites, application deadlines, residency, and total-degree-unit checks using official institutional sources.
4. Incorporate verified course offerings and student availability before offering work-compatible, summer, or variable-load schedules.
5. Prepare course-evaluation requests with transcript, syllabus, and course-description requirements specific to each destination.
6. Recalculate plans when grades, majors, or transfer targets change.

National coverage requires official articulation sources, institutional equivalency and catalog data, and appropriately licensed data access where available. Published equivalencies, planning estimates, and official institutional approvals must remain distinct.

## Validation

Judge progress by whether students can identify their next courses, explain which requirements their coursework satisfies, and find unresolved issues without opening a chat. Measure time to a usable plan, avoidable repeat coursework, and missed requirements. Test with first-year students, students with several prior colleges, students changing majors, and students with work or caregiving constraints.
