# ADR-0012: The web app: one Next.js app for both hosts, guarded routes and a shared design system

- **Status:** Accepted
- **Date:** 2026-10-01
- **Sub-project:** SP-03

## Context

- **Two audiences, one codebase.** Recruiters use the Recruitment Platform on `app.`; candidates use the portal on `candidate.` (master plan §6.2, §6.3). The two must not share cookies or navigation, but they share the design system, the languages and the API client.
- **Every IA route must exist and be guarded** (PRD §7) before the modules that fill them land, and authorisation must hold even where Next's proxy is bypassed (Next's own guidance: the proxy is not an authorisation boundary).
- **Sign-in arrives in SP-02**, but SP-03 and every later sub-project need sessions for every PRD §6 role now.
- **Accessibility and languages** (PRD §101, §102): WCAG 2.2 AA, both themes, keyboard use, en-IN and en-US with no hard-coded text.
- **Security headers** (PRD §82): a strict CSP and no framing.

## Decision

- **One Next.js 16 app, split by host.**
  - `proxy.ts` (Next 16's middleware) rewrites each request onto `app/recruiter/*` or `app/portal/*` by its `Host`. A path from the other host is a 404; an unknown host is 421.
  - `skipProxyUrlNormalize` is on. Without it, Next gives the proxy a URL on a fallback host (`localhost`) that differs from its own, and proxies every rewrite back to itself over the network.
  - Redirects are built from the request's `Host` (already matched against the allow-list) and `X-Forwarded-Proto`, never from `request.url`, which carries that fallback host.
- **Security headers.**
  - Every page gets a fresh nonce. The CSP is `script-src 'self' 'nonce-…' 'strict-dynamic'` (`'unsafe-eval'` only under `next dev`), `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` and `frame-ancestors 'none'`.
  - `style-src` allows `'unsafe-inline'`, because Radix positions popovers with inline styles. Scripts stay nonce-only.
  - `Referrer-Policy: strict-origin-when-cross-origin`, `X-Content-Type-Options: nosniff`, and a `Permissions-Policy` that denies camera, microphone, geolocation and payment.
- **Sessions and guards.**
  - **The contract:** `getSession()` returns `{ user, organization, roles, permissions }` or null. SP-02 serves it at `GET /api/v1/auth/session`; the web app calls `HV_API_INTERNAL_URL` (default `http://127.0.0.1:8000`) with the browser's cookies. Any failure means "not signed in".
  - **The route manifest** (`src/auth/manifest.ts`) lists every guarded page: its permission, its section, its title and the sub-project that fills it. The sidebar, command palette, tabs, proxy and pages all read it. Tests keep it in step with the pages on disk and check that every page guards its own route.
  - **Two checks.** The proxy answers early: an anonymous visitor goes to `/login?next=…`, and a session without the permission gets the Forbidden page with status 403. Each page then checks again (`requireRoute` / `guardedPage`), because a layout isn't re-rendered between its pages and the proxy can be bypassed. Server actions check for themselves.
  - **Development sessions.** One fixture session per PRD §6 role, chosen at `/login` or from the account menu and kept in the `hv_dev_role` cookie.
    - They exist when `HV_WEB_DEV_TOOLS=true`, and by default under `next dev`. `HV_WEB_DEV_TOOLS=false` turns them off.
    - The app refuses to build or start with them on when `HV_ENVIRONMENT=production`.
    - Their permission map is provisional; SP-02's server-side RBAC matrix replaces it.
- **The design system (`packages/ui`).**
  - **Components** are our own, built on Radix primitives and Tailwind v4 tokens, with variants in `cva`. They take every visible string as a prop.
  - **Themes.** `data-theme` on `<html>` switches every token; a nonce'd inline script applies the stored choice before first paint. An organisation's brand colour (SP-22) replaces `--accent` alone.
  - **The data table** is headless TanStack Table v9. Sorting is server-driven and controlled; it adds row selection with bulk actions, column choice, and saved views through a `ViewStore` (browser storage now; SP-22 stores them on the server).
- **Languages.** next-intl without locale URLs: the language is the `hv_locale` cookie, set from the account menu or the portal's language menu.
  - The en-IN catalogue types every `t()` key.
  - A test keeps en-US in step.
  - A lint rule forbids JSX text literals in the app and the design system.
- **Data.**
  - TanStack Query wraps the generated API client, called on the app's own origin (the gateway sends `/api/*` to the backend), so there's no CORS.
  - **Lists:** `useCursorPage` walks the API's forward-only cursors, keeping a stack to go back. Table sort and filters live in the URL.
  - **Failures:** a problem becomes a toast quoting its trace id, or field errors mapped from its RFC 9457 pointers. Only server errors, rate limits and network failures are retried.
- **Testing.**
  - **Vitest** covers logic on Node and components in jsdom.
  - **Playwright** runs against a production build with the development sessions on:
    - every route for every role;
    - axe (WCAG 2.2 AA) on every page in both themes, with no console errors or CSP violations;
    - keyboard paths;
    - the host split.

## Consequences

- **Later sub-projects** add a page by adding a manifest entry and a `page.tsx` that calls `guardedPage` or `requireRoute`. The tests fail if either is missing.
- **SP-02** must serve `/api/v1/auth/session` in the contract's shape. Permissions it sends that this build doesn't know grant nothing.
- **`next dev` signs you in as anyone.** That is deliberate and refused in production. Production builds outside CI must leave `HV_WEB_DEV_TOOLS` unset.
- **The proxy's session lookup** costs one API call per guarded page load. SP-02 can cache it, but the page's own check must stay.
- **Styles.** `'unsafe-inline'` in `style-src` stays until the overlay library stops needing inline styles.
