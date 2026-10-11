# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-monorepo-and-toolchains.md) | One monorepo with uv, pnpm and Cargo workspaces | Accepted |
| [0002](0002-ai-vendors-openai-deepgram.md) | OpenAI and Deepgram APIs for all AI, from day one | Accepted, amended by 0003 |
| [0003](0003-gemini-for-development.md) | Gemini for development and testing, OpenAI for production | Accepted, amended by 0011 |
| [0004](0004-local-stack.md) | Local Docker stack | Accepted |
| [0005](0005-voice-latency.md) | Voice pipeline and measured latency | Accepted |
| [0006](0006-screen-capture.md) | Screen capture and H.264 segment recording | Accepted |
| [0007](0007-webview-media.md) | Camera and microphone recording and face detection in WebView2 | Accepted |
| [0008](0008-livekit-phone-networking.md) | Third-eye phone and desktop on self-hosted LiveKit (local development) | Accepted |
| [0009](0009-tenancy-and-data-foundations.md) | Tenancy, audit log and outbox on PostgreSQL | Accepted |
| [0010](0010-api-conventions.md) | API conventions: problems, pagination, idempotency, rate limits, clock, telemetry, client | Accepted |
| [0011](0011-storage-ai-metering.md) | Blob storage, the AI provider layer and metering | Accepted |
| [0012](0012-web-app-architecture.md) | The web app: one Next.js app for both hosts, guarded routes and a shared design system | Accepted |
| [0013](0013-sign-in-and-sessions.md) | Sign-in and sessions: server-side sessions, the lookup role, CSRF and email | Accepted |
| [0014](0014-organizations-and-access.md) | Organisations and access: custom roles, guards, step-up, scope and the platform | Accepted |
| [0015](0015-jobs-and-documents.md) | Jobs and documents: one documents table, stream workers, verified extraction | Accepted |
| [0016](0016-screening-and-ranking.md) | Screening and ranking: weighted factors, verified evidence, blind by default | Accepted |
| [0017](0017-interview-configuration.md) | Interview configuration: versioned questions and templates, AI drafts for review | Accepted |
| [0018](0018-desktop-device-keys-and-tokens.md) | Desktop sign-in: device-bound keys, DPoP, and tokens kept out of the webview | Accepted |
| [0020](0020-interviews-and-invitations.md) | Interviews and invitations: pinned policy, a lifecycle table, candidate accounts and a cross-tenant scheduler | Accepted |
| [0021](0021-candidate-desktop-auth.md) | Candidate desktop sign-in: DPoP-bound tokens, refresh families, new-device codes and a release registry | Accepted |
| [0030](0030-interview-engine.md) | The interview engine: a deterministic policy over a checkpointed state, one conductor for every turn | Accepted |
| [0031](0031-evaluation-and-governance.md) | Evaluation and AI governance: verified quotes, rubric-weighted scores, pinned versions and a gate | Accepted |
| [0031](0031-proctoring-engine.md) | The proctoring engine: the server decides, what it sees itself is the ground truth, and nothing a reviewer dismisses is deleted | Accepted |

New decisions copy [0000-template.md](0000-template.md) and take the next number.
