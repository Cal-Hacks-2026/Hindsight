# DECISIONS.md — Hindsight decision log

> Every important decision goes here: what we decided, why, and what it costs us.
> Newest at the top. Anyone on the team (and Claude Code) should read this before changing direction.
> Format: **Date/time · Decision · Owner**, then a plain-language paragraph.

---

## D-005 · Sat 2:10 AM · Campus Radar first load takes ~14 seconds (known, being handled) · Atishay

The first time a student opens their Radar feed, the app asks Claude to write a short "why this fits you" line for each top opportunity. Claude writes all of those in one request, and that request takes about 14 seconds. After that, the reasons are saved (cached), so every later visit loads in under half a second. Fourteen seconds on a first visit feels broken to a new user, so we will handle it three ways: (1) the Radar page shows a clear loading state instead of a blank screen, (2) before judging and field testing we open the demo profiles once so their reasons are already cached ("pre-warming"), and (3) if time allows, the API returns the ranked list immediately with simple keyword-based reasons and fills in Claude's reasons a few seconds later, so the student sees results right away.

## D-004 · Sat 2:10 AM · Profiles move from server memory to Supabase · Atishay

Right now, when a student creates a profile and confirms their courses, the API keeps that data only in the server's memory. Memory is wiped every time the server restarts or redeploys, so every profile would disappear, including the profiles field testers create on Saturday. It also blocks a feature: the database table that links a student to their ranked opportunities (`profile_opportunities`) needs the student's profile to exist in the database first. The fix is to save profiles and confirmed courses into the Supabase tables we already created (`profiles` and `transcript_courses`) and read them back from there. The browser keeps the student's profile ID so they return to their own data. This is a small, contained change and must land before we deploy.

## D-003 · Sat 2:10 AM · Droid's self-healing permission is scoped to the scraper page scripts · Atishay

Droid is Factory's AI agent; using it meaningfully is the Factory track. Our plan is for Droid to run on a schedule, scan campus websites for new opportunities, and log every step so judges can see what it did. The stretch goal is "self-healing": campus websites change their layout without warning, which silently breaks the code that reads them (a scan suddenly returns zero events). When that happens, Droid detects the failure, edits the small script that reads that one website, shows the exact change it made (a "diff"), and re-runs the scan. For safety, Droid should only be allowed to edit those reading scripts, nothing else in the codebase. Our original plan put those scripts in `apps/actor/`, but because we switched to a ready-made Apify scraper (see D-002), they now live inside `apps/api/app/services/radar/`. Decision: move the per-site scripts into their own small folder inside Radar and limit Droid's edit permission to exactly that folder. This keeps the safety story clean for the Factory judges, who score "thoughtful control over what Droid can touch."

## D-002 · Sat 1:30 AM · Use Apify's ready-made Cheerio Scraper instead of building our own Actor · Atishay

Apify runs web scrapers ("Actors") in the cloud. There are two Apify prizes: the main track (use Apify meaningfully, up to $2,000) and a separate "Best Actor" award ($400) for an Actor built specifically for this event. With only one person coding, building and publishing our own Actor would cost about three hours. Instead, we use Apify's ready-made **Cheerio Scraper** and write the small per-site scripts that tell it what to pull from each campus page. This keeps us fully eligible for the main Apify track but probably makes us ineligible for Best Actor; we accept that trade. We chose Cheerio Scraper over Apify's "Website Content Crawler" because the crawler returns only plain page text, which would force us to guess event dates. Cheerio Scraper returns each site's structured data, so every date and link comes directly from the source, and a missing date stays empty instead of being invented. Apify usage is covered by the $205 Cal Hacks credit.

## D-001 · Fri 10:15 PM · One coder, parallel Claude Code sessions, Atishay integrates · Atishay

Only Atishay is writing code this weekend. To keep pace, he runs two or three Claude Code sessions in parallel, each in its own git worktree (a separate copy of the repo on its own branch), each working on a different part of the app. Every session opens a pull request; Atishay reviews and merges each one, and nobody pushes directly to `main`. Shiv, Amaan, and Dhana handle non-code work (requirements data, campus sources, interviews, sponsor booths, Devpost, video).
