# SP-03 Web shell and design system: design

- **Date:** 2026-09-29
- **Status:** Approved (visual direction and architecture chosen by the product owner on 2026-09-29)
- **Master plan:** §14 SP-03, §6.2, §6.3, D3, §13 (UX), PRD §7, §10, §72, §101, §102

## Goal

Build the recruitment platform's frame, which every later web feature plugs into:
- one design system;
- the application shell with every PRD §7 section;
- guarded route skeletons;
- the data-table and form frameworks;
- the dashboard layout;
- the candidate portal's separate host;
- language and accessibility baselines, checked in CI.

## Decisions

- **One Next.js 16 app, two hosts.**
  - `recruitment-platform/` (App Router, React 19.3, TypeScript 7) serves both hosts:
    - `app.hirevion.localhost`, the recruiters' app;
    - `candidate.hirevion.localhost`, the candidate portal.
  - `proxy.ts` rewrites each host into its own route group, and a request for the other host's routes is a 404. Caddy already sends both hosts to port 3000, and `/api/*` on the app host to the API (same origin, no CORS).
  - Next 16 type-checks correctly with TypeScript 7 (verified: `next build` fails on a type error).
- **Visual direction: calm professional.**
  - **Palette:** slate neutrals and one deep indigo accent.
  - **Type:** Inter (self-hosted with `@fontsource-variable/inter`, no font CDN) at a 14 px base, with compact tables.
  - **Theme:** light by default, a full dark theme, and the system preference respected. The choice is stored per browser.
- **Design tokens** are CSS custom properties exposed to Tailwind v4 through `@theme`:
  - neutrals, accent, the semantic colours (success, warning, danger, info) and the proctoring severities (INFO, WARNING, CRITICAL);
  - radii, spacing, shadows and focus ring.
  - Everything accent-coloured reads `--accent`, so an organisation's brand colour (PRD §9, set in SP-22) replaces it in one place.
  - Both themes meet WCAG 2.2 AA contrast, checked by axe.
- **`packages/ui`** holds our own components, shadcn-style: source in the repo, built on Radix primitives (`radix-ui`), with `class-variance-authority` and `tailwind-merge`. It contains:
  - **Basics:** Button, IconButton, Input, Textarea, Select, Checkbox, RadioGroup, Switch, Label.
  - **Forms:** FormField, which wires react-hook-form and zod and shows the error with `aria-describedby`.
  - **Overlays and navigation:** Dialog, Sheet, DropdownMenu, Popover, Tooltip, Tabs.
  - **Display:** Badge, Card, Avatar, Skeleton, EmptyState, Breadcrumbs, KpiTile.
  - **Feedback and commands:** Toast (Sonner), CommandPalette (`cmdk`).
  - **DataTable** (TanStack Table), with:
    - column definitions;
    - server-side sorting and filtering through URL search parameters;
    - cursor pagination (`next_cursor`, SP-01b);
    - row selection with a bulk-action bar;
    - column visibility;
    - saved views.

    Saved views are stored in the browser through a `ViewStore` interface; a server store can replace it later.
  - Icons are `lucide-react`. A development-only gallery page shows every component in both themes and is axe-tested.
- **The shell** (recruiter host):
  - **Sidebar:** Dashboard, Jobs, Candidates, Interviews, Question Library, Reports, Administration, and Platform for the super admin. It collapses to icons.
  - **Top bar:** the command palette (Ctrl/⌘+K, also route search), a notification bell opening the notification-centre panel (empty until SP-18), and the user menu (theme, language, sign out).
  - **Around the content:** breadcrumbs; a skip-to-content link; visible focus rings; and `g`-prefixed keyboard shortcuts (`g d` dashboard, `g j` jobs, `g c` candidates, `g i` interviews).
- **Routes.** Every item in PRD §7 and master plan §6.2 exists. Each renders a page header, its tabs, and an empty state naming the sub-project that fills it.
  - `/dashboard`
  - `/jobs` (tabs All, Draft, Open, Paused, Closed, Archived) and `/jobs/new`
  - `/candidates` (tabs All, Screening, Shortlisted, Interview, Completed, Final decision)
  - `/interviews` (Upcoming, Live, Completed with the pending-review queue, Templates)
  - `/questions` (Technical, Coding, System design, Resume-based, Custom)
  - `/reports` (Interview, Proctoring, Candidate, Analytics)
  - `/admin/*`: Organisation, Users, Roles, Teams, Departments, AI, Integrations, Security, Proctoring policies, Retention and DSR, Branding, Webhooks, API keys, Usage and cost, Audit logs
  - `/platform/*`: Organisations, AI, Security, App catalogue, Desktop releases, Audit, Health
  - `/notifications`, `/login` and `/forbidden`
- **The dashboard** has:
  - the ten PRD §10 KPI tiles, showing "—, no data yet" until their modules land;
  - the seven filters (date range, recruiter, team, job, department, candidate status, interview status), kept in the URL;
  - the hiring-pipeline board, with a column per PRD §72 status (Under review, Shortlisted, Interview invited, Interview started, Interview completed, Additional review, Selected, Rejected, On hold). It supports keyboard focus now; moving cards arrives with data in SP-05/SP-17.
- **Sessions and guards.**
  - **The contract:**
    - `getSession()` returns `{ user, organization, roles, permissions }` or `null`. SP-02 serves it from `GET /api/v1/auth/session`.
    - A route manifest lists every route with the permission it needs.
  - **The recruiter layout** redirects anonymous visitors to `/login`.
  - **Section layouts** call `requirePermission()`. A missing permission renders the Forbidden page with HTTP 403.
  - **Navigation and the command palette** show only what the session may open.
  - **Server actions** re-check permissions themselves; the proxy is never trusted for authorisation (Next.js guidance).
  - **Until SP-02, development sessions:**
    - When `HV_WEB_DEV_TOOLS=true`, a switcher offers one fixture session per PRD §6 role (super admin, org admin, recruiter, hiring manager, interviewer).
    - The app refuses to start with that variable set when `HV_ENVIRONMENT=production`.
    - The fixtures' role-to-permission map is provisional; SP-02's server-side RBAC matrix becomes the source of truth.
- **Data.**
  - TanStack Query wraps `@hirevion/api-client`.
  - `ApiProblem`s become inline field errors (`errors[].pointer`) or toasts naming the trace id.
  - A `useCursorPage` hook drives DataTable pagination.
- **Language (PRD §102).**
  - next-intl, with message catalogues for en-IN (the default: lakh/crore digit grouping, DD/MM dates) and en-US.
  - The locale comes from the user menu (a cookie), not the URL.
  - No user-visible string is hard-coded. A test fails when the two catalogues differ in keys, and a lint rule flags JSX text literals.
- **Accessibility (PRD §101, WCAG 2.2 AA).**
  - Semantic landmarks and one `h1` per page.
  - Every control labelled; focus kept visible and never trapped except inside dialogs.
  - `prefers-reduced-motion` respected.
  - Colour never the only signal: severity badges carry text.
- **Security headers:**
  - a strict Content-Security-Policy with a per-request nonce, set in `proxy.ts`;
  - `frame-ancestors 'none'`, `Referrer-Policy: strict-origin-when-cross-origin`, a restrictive `Permissions-Policy`, and `X-Content-Type-Options: nosniff`.
- **The candidate portal (master plan §6.3)** has its own minimal layout (logo, language, no recruiter navigation) and placeholder pages: accept invitation, set password, download the app, notices, interview status, report, and requests. SP-07 fills them.
- **Testing and CI.**
  - Vitest and Testing Library cover components, hooks, the permission logic and the message-catalogue parity.
  - Playwright against a production build (`next build` then `next start` with development sessions on) checks:
    - every route for every role (renders or is refused correctly);
    - axe on every route in light and dark, with no violations;
    - a keyboard-only walk through the shell (skip link, sidebar, command palette, a menu, a dialog);
    - no CSP violations on any route;
    - the host split between recruiters and candidates.
  - A new CI `web` job runs lint, typecheck, unit tests, build and Playwright with Chromium.

## Out of scope (and where it goes)

- **Login, sessions, MFA and the real RBAC matrix:** SP-02.
- **Real data** in lists, KPIs and the board: the module that owns it (SP-04 onwards).
- **Charts:** SP-21 (analytics), which adds the ECharts wrapper with table equivalents.
- **Notification delivery:** SP-18. Organisation branding values: SP-22.
- **Portal flows:** SP-07.

## Risks

- **Next 16 renamed middleware to `proxy.ts` (Node runtime).** Its tests use `next/experimental/testing/server`, which may change; the Playwright host-split test covers the same behaviour end to end.
- **A nonce-based CSP makes every page dynamically rendered.** That's acceptable: every page depends on the session anyway.
