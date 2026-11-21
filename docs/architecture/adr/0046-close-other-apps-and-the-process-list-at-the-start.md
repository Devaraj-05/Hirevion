# ADR-0046: Close other apps before Start, and save the process list the interview starts with

- **Status:** Accepted
- **Date:** 2026-11-21
- **Sub-project:** C8-6 (desktop app, interview API, proctoring)

## Context

After the spoken run of 2026-11-21 the product owner asked:

- "are you taking how many process that running in the background for that candidate pc/laptop … ask the candidate to close all the background and other applications";
- "background process list should be saved at a time".

What existed:

- The desktop read every running process when monitoring started, but saved only those the blocked-apps policy matched (`BLOCKED_PROCESS_DETECTED`). The owner's run saved 14 of them at the start (ChatGPT, Claude).
- Nothing asked the candidate to close anything before Start.
- An event's `details` are bounded at 40 list items and 8 KB, so a full process list (about 280 processes on the owner's PC) can't travel as plain details. PRD §67 has an evidence kind for it, `process_metadata`, which the server already stores as JSON (`proctor_evidence.ref`).

## Decision

### The apps check before Start

- **The rules:**
  - The briefing (`GET /interviews/{id}/briefing`) now carries `app_rules`: the proctor session's pinned ones once it exists, and before that the ones `build_policy` would pin now. So a rule changed since the session opened never makes the check differ from what the interview reports.
  - It is `null` when the policy doesn't check processes (`processes` isn't among its checks: the `off` and `basic` levels).
- **What it lists:** the desktop's `apps_to_close` command lists the running processes and matches them with the monitor's own `PolicyMatcher` (`hv_event_queue::apps_to_close`). Each app appears once:
  - **blocked**, which must be closed: a blocked app showing a window;
  - **background**, which is reported but never holds Start back: a blocked app without a window, such as a service or a tray app the candidate may not be able to stop;
  - **open**, which is any other app with a window, advised closed.
  - Left out: processes without a window, the Windows shell (Explorer, the Start menu, search…) and the interview app itself.
- **Speed:**
  - Hashing and verifying every executable took 31 s for 283 processes on the owner's PC, mostly reading large executables twice.
  - The check therefore reads the files of programs in Windows' protected folders (`System32`, `SysWOW64`, `WinSxS`…, never `Temp`) only when a rule's name, path or window-title conditions already hold and only the file can decide (`PolicyMatcher::needs_file_facts`; for example Hyper-V's `vmconnect` with publisher Microsoft).
  - It hashes a file only when a rule compares hashes, and verifies the rest in parallel.
  - A rule on a name, a path or a window title applies to every process. A publisher-only rule doesn't reach Windows' protected folders before Start, and the monitor checks everything in full once the interview starts.
  - The check starts with the system check, so its few seconds pass while the candidate answers the sound question.
- **On the page:**
  - When the system check passes, step 2 shows the blocked apps under "Close these apps to continue", with "Check again". The step isn't done, so Start stays locked, until none is running.
  - Other open apps are listed under "Close your other apps", with "Check again" and "Continue".
  - Blocked background apps are listed with a note, and never hold Start back.
  - If the check can't run, the candidate is asked to close every other app themselves, with "Check again" and "Continue". The failure is logged, and the monitor still reports blocked apps during the interview.
  - A look started with the system check is used only if it is under 10 seconds old; otherwise the apps are looked at again, in case one was opened meanwhile.

### The process list at the start

- **On the desktop:**
  - Each start of monitoring (the interview's start, and a resume after a crash) ends its first poll with one `ProcessInventory` observation: every process running then, the interview app's own left out. The report calls it "Apps running when monitoring started".
  - The rules turn it into one `PROCESS_INVENTORY` event (INFO, check `processes`) with `{count, processes: [{name, path, publisher, window_titles}]}`.
  - The device applies the server's bounds and a 192 KiB budget (`truncated` when cut), so a batch with it stays under the API's 1 MiB.
  - A publisher is sent only from a valid signature.
  - The event goes through the event queue like every other event, so it is saved as soon as the interview starts, not at submit.
- **On the server:**
  - It moves the list out of the event's details into a `process_metadata` evidence row linked to the event, kept whole: up to 2,000 processes, each with those four fields only, strings at most 300 characters, at most 5 window titles.
  - The event's details keep `count` and `windows` (the names of the processes with a window).
  - The proctoring report's evidence shows "N running processes".

### Tests that simulate a whole interview

- Since C8-4 an interview asks until its time is used, and the simulator answers instantly. A simulated 30-minute interview therefore sent more than the 30 answers a minute the API allows (`429`), and ten API tests had failed since then.
- The API's conductor and the coding-telemetry check now take the interview's clock from `app.state.interview_clock`, which tests set and production never does.
- The tests' `paced` fixture moves that clock two minutes per answer, as the conductor tests already did, and stamps the simulator's events with it, as the desktop stamps them with server time.

## Consequences

- A candidate can't start with a blocked app running. The interview starts with a recorded list of what else was running, which the reviewer can compare with later `BLOCKED_PROCESS_DETECTED` and focus events.
- **Pre-check limitations:**
  - It doesn't hash or verify Windows' own programs, so a rule on the publisher or hash of a program in the Windows folder is applied only by the monitor during the interview.
  - Closing apps is the candidate's job: the app never closes another program.
- **Privacy:** the list holds executable names, paths, publishers and up to 5 window titles each, under the consent's `system_telemetry` purpose. Window titles can name documents or mail subjects, which is why only the first five per process are kept.
- **Verified:**
  - Rust tests for the inventory observation, the inventory event, the apps-to-close matcher, `uses_hash`, and the stub.
  - A live Windows test of `running_processes`.
  - Python tests for the inventory evidence, the splitter, the report, the briefing's rules, and the API contract.
  - The desktop e2e: ChatGPT blocked, Check again, the advice, Continue.
  - A Playwright review at four sizes in light and dark.
- **Still to check:** the owner's run with ChatGPT open (C8-2).
