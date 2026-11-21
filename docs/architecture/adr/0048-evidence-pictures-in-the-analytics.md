# ADR-0048: The evidence pictures in an interview's analytics, for the hiring team only

- **Status:** Accepted
- **Date:** 2026-11-22
- **Sub-project:** C8-8 (recruiter web app)

## Context

The product owner, after C8-7's Analytics tab: "not on the candidate page i said for the admin or recruiter can able to see the analytics. screenshots taken during the interview found any malpractice etc. we dont show anything for the candidate."

The Analytics tab is on the recruiter app's candidate page, a staff page: the candidate portal has no analytics and never shows proctoring. What the tab lacked was the pictures.

The pictures already exist:
- The desktop takes a screen or webcam snapshot when the server asks for one at a critical event (B4b-1a).
- The vision agent keeps the phone camera's frame when it sees a phone or a second person (C7-1).
- `GET /proctoring/{interview_id}/evidence` lists them with five-minute signed links. It needs `reports.proctoring.view`, and each look is audited as `proctoring.evidence_viewed`.

In the browser, the recruiter app's Content Security Policy allowed images only from its own origin (`img-src 'self' data: blob:`), so a signed link to storage could never show.

## Decision

- **Where:** in the Analytics panel's Integrity part (ADR-0047), between the timeline and the process list. The Integrity part shows only for `reports.proctoring.view` holders, which interviewers and candidates are not.
- **When they load:** only when the recruiter presses "Show the evidence pictures". Each look is audited, so opening the tab isn't one, and the list never reloads by itself (not on focus, not on reconnect). It is kept for four minutes, under the links' five.
- **What shows:**
  - each picture that belongs to an event, in the order of the interview;
  - its event with the severity dot, where it came from (Screen, Webcam or Phone camera), its time from the start, and a reviewer's decision when there is one;
  - a click opens the full picture in a new tab;
  - a picture that fails to load says so instead of showing a broken image: "Couldn't load the picture. It may never have been uploaded." (a browser can't tell a missing blob from other failures);
  - a picture failing once its link is about to expire (from 4.5 minutes) says "The link has expired", with "Load the pictures again" above the list: a new, audited look with fresh links, which retries every picture;
  - snapshots the server asked for but the desktop never sent have no picture; a line counts them.
  - a line saying the pictures are for the hiring team only, every look is recorded, and links expire after five minutes.
- **The CSP:** on the recruiter host only, `img-src` and `media-src` add the storage origin from `HV_STORAGE_PUBLIC_ORIGIN`. Under `next dev` it defaults to `https://storage.hirevion.localhost`; elsewhere there is no default, so a deployment must set it. Only an http or https origin is used: a path is dropped, and a wildcard, another scheme or an empty value adds nothing. `connect-src` and `default-src` don't change, and the candidate portal's policy doesn't change at all.

## Consequences

- A recruiter or an admin sees what was caught, beside the event that caught it. Candidates see nothing new.
- A deployment sets `HV_STORAGE_PUBLIC_ORIGIN` to the origin of its `STORAGE_PUBLIC_ENDPOINT` (the cloud plan's web settings); without it, every picture says it couldn't be loaded. On this PC it is `http://127.0.0.1:10000`, with the API started as the runbook says.
- The owner's interview of 2026-11-21 shows 45 pictures: the 5 phone-camera frames, and 40 desktop snapshots that couldn't be loaded, because that run's uploads had nowhere to go (ADR-0045).
- **Verified:**
  - Web tests: the pictures load only when asked; their source, time and link; a picture that fails says so; an expired link offers a reload that brings fresh links; untaken snapshots are counted and untimed pictures go last; the CSP takes only a clean origin, into `img-src` and `media-src`, on the recruiter host, with the local default only in development.
  - Playwright on the owner's interview at 1440 px in light and dark: 45 pictures, 5 loaded, 40 marked, no sideways scrolling, no errors.
