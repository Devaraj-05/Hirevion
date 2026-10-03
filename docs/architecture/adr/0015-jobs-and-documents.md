# ADR-0015: Jobs and documents: one documents table, stream workers, verified extraction

- **Status:** Accepted
- **Date:** 2026-10-02
- **Sub-project:** SP-04a (resumes follow in SP-04b)

## Context

- **PRD §11** asks for jobs with their fields and five statuses. **§12** asks for a job-description pipeline (validate, scan, extract, normalise, sections, skills, requirements, experience, embed, profile) with recruiter review. **§13–14** ask for the resume pipeline that SP-04b builds on the same parts.
- **Master plan §2 D2** planned a Celery worker for background work. SP-01 already delivers events through a transactional outbox and Valkey streams, and SP-02a's mail consumer showed the pattern works.
- **Master plan §3.2(3)** requires every AI-extracted item to be machine-checked against the source text.
- **§6.6** planned Presidio for PII. The product owner chose built-in recognisers instead.

## Decision

- **Documents:**
  - **One `documents` table** for job descriptions and resumes. It holds kind, file name, content type, size, SHA-256, blob path, status, error code, attempts, the extracted text, page count, flags and the extraction.
  - **Statuses:** `uploaded` → `scanning` → `extracting` → `parsing` → `parsed`, or `quarantined` / `failed`. Each step commits on its own, so the page shows progress.
  - **Files** are typed by their magic bytes (PDF, DOCX, TXT; images in SP-04b), limited to 10 MB and 50 pages, and stored under ADR-0011's paths. Pasted text needs no file.
  - **ClamAV** scans every file over INSTREAM. An infected file moves to `<org>/quarantine/…`, is never read, and the document ends `quarantined`. `HV_DOCUMENTS_SCAN=false` turns scanning off, but never in production.
- **Background work runs on stream consumers, not Celery (replaces D2's worker):**
  - **The flow:** a submit or retry writes a `documents` outbox event in the request's transaction; the relay publishes it to `hv:events:documents`; the `documents` consumer group processes it.
  - **Delivery:** the same rules as mail. Delivery is at least once; an event id is remembered for a week so a repeat is dropped; a failed event is reclaimed after 60 s; after five deliveries it moves to `hv:dead:documents` and the document is marked failed (`retries-exhausted`).
  - **Outages** (scanner down, AI unavailable) leave the document where it stopped and re-raise, so the event is retried. A bad file ends `failed` with a reason, and a recruiter can retry it.
  - **Where it runs:** inside the API process (`HV_API_RUN_WORKERS`) or alone with `hv worker`.
  - **Resilience:** a server without blob storage or AI keys still relays the outbox and sends email. Uploads answer 503 `storage-unavailable`, and documents aren't processed.
- **Extraction with verified quotes:**
  - **One structured call** per description (purpose `jd.extract`, prompt `jd-extract-v1`, strong tier). The description goes in as data between tags, never as instructions.
  - **Every item carries a quote.** A quote not found in the text, after folding case, whitespace, quote marks and dashes, drops its item. The count of dropped items is shown in the review.
  - **Skills** are matched to the shared taxonomy (207 skills, 181 aliases, seeded by migration); unknown skills stay as free text.
  - **The extraction stays on the document.** "Apply" writes the recruiter's reviewed version into the job as a new version (`jd-applied`) and re-embeds the job (1536 dimensions, pgvector).
- **Jobs:**
  - **Numbers:** `JOB-0042`, unique per organisation.
  - **Transitions:** Draft → Open; Open ⇄ Paused; Open or Paused → Closed; Closed → Archived. Opening needs a title, a description and a required skill.
  - **Versions:** every change writes a `job_versions` snapshot and an audit entry.
  - **Scope:** a job belongs to a team and a recruiter, so ADR-0014's scope applies to every read and change. Outside the scope, a job doesn't exist (404).
  - **Permissions:** `jobs.view` reads; `jobs.create` ("Create and edit jobs") changes.
- **PII (for SP-04b):** built-in recognisers, not Presidio: Aadhaar (12 digits with a Verhoeff checksum), PAN, phone, email and date of birth. Aadhaar and PAN are masked to their last four characters before text is stored or sent to an AI service.
- **Accuracy target (measured in SP-04b):** field-level F1 ≥ 0.90 overall and ≥ 0.95 for name, email and phone, on the synthetic resume set, with Gemini.
- **Testing:** the mock AI profile answers a purpose from `HV_AI_MOCK_SCRIPTS`, a JSON file, so the end-to-end suite reads a description deterministically.

## Consequences

- **No new infrastructure:** Celery and a broker aren't needed, and documents use the same delivery, retry and dead-letter rules as mail. Scaling out means more consumers in the group.
- **Scheduled work** (SP-18, SP-22) will need its own scheduler, since there is no Celery beat.
- **Hallucinated items can't reach a job unseen:** they are dropped, counted and shown. The review step keeps a human between the AI and the screening profile (PRD §2).
- **Watch:**
  - the dead-letter stream and `retries-exhausted` documents;
  - AI cost per description (`ai_invocations`);
  - ClamAV's signature updates on first start.

## Addendum: resumes and candidates (SP-04b, 2026-10-03)

- **Resumes** use the same table, consumer and statuses, plus `ocr`:
  - PDF, DOCX, TXT, JPG, PNG and TIFF files of up to 10 MB;
  - ZIP archives (kind `archive`) of up to 50 MB, at most 200 entries, 200 MB uncompressed and a compression ratio of 100. Nested archives and other types are skipped with a reason.
  - An archive isn't scanned whole: each entry becomes a resume document of its own and is scanned before anything reads it, so one infected file doesn't sink a batch.
- **Hidden text** is left out of what the AI reads and flagged: white, sub-3-pt or off-page PDF text, and hidden, white or tiny Word runs. So are zero-width characters, long metadata and instruction-like phrases ("ignore previous instructions", "rank me first"). The flags reach the candidate, and recruiters see them.
- **OCR:**
  - images, and PDF pages with almost no text layer (rendered at 200 dpi), go to the OCR service one page at a time;
  - a page image can't be masked before it's read, so it goes to the OCR service unmasked; its text is masked before it's stored or parsed;
  - OCR call records keep only the character count and confidence, never the text.
- **PII:** the built-in recognisers mask Aadhaar and PAN before storage and before the parse. The parse also requires the email and phone it returns to be ones the text contains.
- **The parse** (`resume.parse`, prompt `resume-parse-v1`) returns PRD §14's fields. Every item carries its quote, and the page and section it came from.
- **De-duplication:** the same email, then the same phone, then a near-identical name (trigram similarity of at least 0.92) with no conflicting contact. A similar name with a conflicting contact is a new candidate flagged `possible_duplicate_of`. An exact copy of a resume already parsed reuses that result, with no AI call.
- **Candidates and applications:** the latest resume sets the candidate's profile, skills (normalised to the taxonomy) and embedding. Each job a resume is uploaded to gets an application at stage `parsed`. Reads go through the resource scope via the applications' jobs. Downloads are 5-minute signed links, audited for resumes.
- **The evaluation** (`hv synth-resumes`, `hv eval-resumes`) runs the real pipeline over 200 synthetic resumes with true values and scores 14 fields.
  - **Checked so far (mock AI, 2026-10-03):**
    - all 200 reach a final status;
    - ClamAV quarantines EICAR;
    - all 10 injection samples are flagged;
    - no raw Aadhaar number is stored in documents, candidates or AI records;
    - the 10 ZIP copies are reused without an AI call.
  - **Not yet measured:** the F1 targets, which need a live run with a valid Gemini key (`docs/evals/2026-10-resume-parse.md`).
