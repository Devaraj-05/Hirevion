# Product

<!-- impeccable:product-schema 1 -->

The source of truth for every requirement is `AI_Recruitment_Platform_Complete_PRD.md` at the repository root. This file records only what design work on the candidate desktop app needs, as confirmed by the product owner (2026-11-22, 2026-11-24).

## Platform

web

The Hirevion candidate app is a Windows desktop app built with Tauri: a React webview (React 19, Tailwind 4, `@hirevion/ui` tokens) inside a native shell. There is no browser chrome, and the window opens maximised and can shrink to 800×600.

## Users

Candidates invited to a timed, monitored AI interview, on their own Windows laptop. They are often nervous, alone, and being recorded, with a phone set beside the laptop as a second camera (Third-Eye). Each interview can be taken once.

## Product Purpose

Run a natural, real-time AI voice interview fairly and securely. On the interview screen, success means the candidate always knows who is talking, what was said, how much time is left, that both cameras are working, and how to end, and nothing distracts them from answering.

## Operating Context

- **The interview:** a voice interview with an AI interviewer over LiveKit, with a live transcript of both speakers.
- **Coding question:** one, only when the recruiter turned it on when scheduling. It is typed into a text box (never run) and reviewed after the interview. A design question gets a plain notes pad.
- **Monitoring:** the main webcam and the phone's camera are recorded, and the screen is recorded too. Proctoring watches for other people, phones and blocked apps.
- **One attempt:** one reconnect, within 2 minutes, from the same laptop. End Interview, or closing the window, ends the interview for good.

## Capabilities and Constraints

- **No new dependencies** in the desktop webview. Animation uses CSS keyframes, with no motion library.
- **Text mode** (an accommodation or a voice failure) replaces speaking with an answer box.
- **What the server owns:** the time left, a question's workspace (`code`, `whiteboard`, `none`) and the interviewer's voice state.
- **Captions** come from LiveKit `lk.transcription` text streams.

## Brand Commitments

- **Product name:** Hirevion. The interview screen's mark is an original waveform emblem with the wordmark "AI INTERVIEW". It is not derived from any existing product's logo.
- **Owner's direction (binding, 2026-11-22):**
  - an Apple-inspired, calm, premium look: light, cool gray, with blue and violet accents used sparingly;
  - a top bar with the candidate's name, job and "Interview", the countdown, and a clear End Interview that confirms first;
  - three columns: coding (only when asked), the AI voice orb with the live transcript, and the main and side cameras with a "CONFIDENTIAL • INTERVIEW SESSION" watermark.

## Evidence on Hand

- **Data:** synthetic interviews only.
- **Not provided:** no photography, illustrations or testimonials, and none may be invented.

## Product Principles

- Calm over clever: the candidate is under pressure, so nothing moves or speaks without a reason.
- Always say what is happening, in text as well as colour: who's speaking, whether the cameras are live, how long is left.
- Ending is deliberate: the one destructive action confirms and says it can't be undone.
- Fair to everyone: text mode, captions and accommodations are first-class, not fallbacks.

## Accessibility & Inclusion

- **WCAG 2.2 AA** (PRD §101): captions and transcript, keyboard operation, visible focus.
- **System preferences:** honour `prefers-reduced-motion`, `prefers-reduced-transparency`, `prefers-contrast: more` and Windows High Contrast (`forced-colors`).
- **Status is never colour alone.**
