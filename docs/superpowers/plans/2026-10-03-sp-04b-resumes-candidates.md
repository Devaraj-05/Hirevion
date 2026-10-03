# SP-04b Resumes and Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The resume pipeline (PRD §13–14). Single, bulk and ZIP uploads of PDF, DOCX, TXT, JPG, PNG and TIFF files become de-duplicated candidates with an evidence-backed parsed profile and an application to the job. This plan also delivers the 200-resume synthetic set and the extraction F1 evaluation. See `docs/superpowers/specs/2026-10-02-sp-04-jobs-documents-design.md` and ADR-0015.

**Architecture:**
- **Reuse:** SP-04a's `documents` table and consumer. A resume goes through the same `process_document`, which branches by kind:
  - `resume` → OCR when needed → safety checks → PII masking → parse → candidate;
  - `archive` → validate and scan the ZIP → one child `resume` document per entry.
- **`hirevion_core.candidates`** owns candidates, their skills, applications, de-duplication and the profile build.
- **The API** adds resume upload and listing per job, applications per job, candidates, and a resume download.
- **The web app** adds the job page's Resumes and Candidates tabs, the `/candidates` list and a candidate page (the Profile and Resume tabs of Candidate 360; SP-17 adds the rest).

**Tech Stack:**
- **Existing:** pdfplumber and pypdfium2 (also render scanned pages), Pillow (via pdfplumber), python-docx, pgvector and pg_trgm; the AI layer (`complete`, `embed`, `ocr.read_page`).
- **New, development only:** reportlab (BSD) and Faker (MIT) to generate the synthetic resumes; rapidfuzz (MIT) to score them.

## Global Constraints

- **Master plan §13 applies to every task:**
  - UUIDv7 keys, UTC `timestamptz`, row-level security and composite foreign keys;
  - RFC 9457 problems, cursor pagination and `Idempotency-Key` on creates;
  - en-IN and en-US strings, WCAG 2.2 AA, TDD;
  - every route in the authorisation matrix.
- **Untrusted text is data.** A resume goes to the AI between `<resume>` tags with that instruction. Every parsed item needs a quote found in the text; items without one are dropped and counted.
- **PII (ADR-0015):**
  - Aadhaar numbers (12 digits, Verhoeff-valid, first digit 2–9) and PANs are masked to their last four characters before the text is stored or sent to any AI service.
  - No raw Aadhaar number is stored anywhere: not in `documents.text`, the extraction, candidates or logs.
- **Hidden text** is excluded from what the AI reads and flagged:
  - white or near-white text, text under 3 pt and text off the page (PDF);
  - hidden, white or tiny runs (DOCX);
  - zero-width characters;
  - long metadata text.
- **Prompt-injection phrases** in the visible text are flagged, never obeyed.
- **Files:**
  - each file at most 10 MB, typed by magic bytes;
  - a ZIP at most 50 MB, with at most 200 entries, 200 MB uncompressed in total and a compression ratio under 100, and no nested archives (skipped, with the reason);
  - images at most 25 megapixels;
  - at most 50 pages.
- **Scope:** a team-limited user sees the candidates who applied to jobs they reach (`scope_clause` through `applications` → `jobs`).
- **Audit (PRD §97):** `resume.uploaded`, `candidate.created`, `candidate.merged` (when de-duplication adds to an existing candidate) and `candidate.resume_downloaded`.
- **Git:** commit as Devaraj-05 only, with no AI attribution.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/migrations/versions/0010_candidates.py` | `candidates`, `candidate_skills`, `applications`; `documents` gains `candidate_id`, `parent_id`, kind `archive` and status `ocr`; the new permission |
| `backend/core/src/hirevion_core/models/candidate.py` | `Candidate`, `CandidateSkill`, `Application` |
| `backend/core/src/hirevion_core/documents/{pii,hidden,ocr,archive,resume}.py` | Recognisers and masking; hidden-text and injection detection; OCR of images and scanned pages; ZIP expansion; resume parsing |
| `backend/core/src/hirevion_core/documents/prompts/resume-parse-v1.md` | The versioned resume prompt |
| `backend/core/src/hirevion_core/documents/{intake,pipeline,text}.py` | Resume and ZIP intake; the pipeline's resume and archive branches; per-page text with hidden-text exclusion |
| `backend/core/src/hirevion_core/candidates/{__init__,dedupe,profiles,candidates}.py` | Matching, the profile build, listing and reading with scope |
| `backend/api/src/hirevion_api/candidates/{__init__,schemas,routes}.py` | `/jobs/{id}/resumes`, `/jobs/{id}/applications`, `/candidates`, `/candidates/{id}`, `/documents/{id}/download` |
| `recruitment-platform/src/candidates/**`, `src/jobs/{resumes-panel,applications-panel}.tsx`, `src/app/recruiter/(shell)/candidates/**` | Upload and processing, the candidate lists, the candidate page |
| `tools/devcli/src/hirevion_devcli/{synthetic_resumes,resume_eval}.py` | `hv synth-resumes` and `hv eval-resumes` |
| `docs/evals/2026-10-resume-parse.md`, ADR-0015 amendment, runbook, master plan Appendix A | Results and docs |

---

### Task 1: Schema for candidates and applications

**Interfaces (produces):**
- **`Candidate`** (`candidates`), tenant-scoped:
  - columns:
    - `name`;
    - `email` (citext, nullable), `phone` (text, digits only, nullable), `location`, `headline`;
    - `profile` (jsonb: the latest verified extraction, with evidence);
    - `flags` (jsonb: `possible_duplicate_of`, injection and hidden-text flags carried from documents);
    - `embedding` (vector(1536), nullable);
    - `resume_document_id`, `created_by`, timestamps;
  - indexes: unique (`organization_id`, `email`) where `email` is not null; (`organization_id`, `phone`); a trigram index on `name`.
- **`CandidateSkill`** (`candidate_skills`): `organization_id`, `candidate_id`, `position`, `name`, `skill_id` (nullable), `years` (numeric(4,1), nullable); primary key (`candidate_id`, `position`).
- **`Application`** (`applications`), tenant-scoped:
  - columns: `candidate_id`, `job_id`, `document_id`, `stage` (`uploaded|parsed|screened|ranked|review|shortlisted|rejected|on_hold`; SP-05 drives it past `parsed`), `source` (`upload`), `created_by`, timestamps;
  - unique (`organization_id`, `job_id`, `candidate_id`).
- **`documents`:**
  - adds `candidate_id` and `parent_id` (both nullable; composite foreign keys);
  - kind adds `archive`; status adds `ocr`;
  - an index on (`organization_id`, `sha256`).
- **Permission `candidates.manage`** ("Upload resumes and manage candidates"), held by `org_admin` and `recruiter`.

- [ ] **Steps:**
  - failing tests (`tests/db/test_candidates_schema.py`):
    - the three tables are tenant-isolated;
    - an application can't point at another organisation's job or candidate;
    - two candidates can't share an email in one organisation, but can across organisations;
    - the isolation harness reports no problems;
  - implement the migration (follow 0009's helpers), the models and the permission (catalogue, roles, en-IN and en-US labels, the roles-panel test);
  - commit `feat(candidates): add candidates, skills and applications`.

### Task 2: PII recognisers and masking

**Interfaces** (`documents.pii`):
- `find(text) -> list[PiiMatch(kind, start, end, value)]`, where `kind` is one of:
  - `aadhaar`: 12 digits, optionally in 4-4-4 groups, first digit 2–9, Verhoeff-valid;
  - `pan`: `[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]`;
  - `phone`: Indian mobile (`+91`/`0` optional, 10 digits starting 6–9) or E.164;
  - `email`;
  - `dob`: a date within 30 characters after "DOB", "Date of Birth" or "Born".
- `verhoeff_valid(digits) -> bool`.
- `mask(text) -> Masked(text, counts)`: Aadhaar and PAN become `XXXX XXXX 1234` and `XXXXXX234F`; the other kinds are left in place and counted.
- `normalise_phone(text) -> str | None`: the digits, with India's `91` prefix dropped from 12-digit numbers.

- [ ] **Steps:**
  - failing tests (`tests/test_pii.py`):
    - Verhoeff accepts the published test vectors and rejects one changed digit;
    - a valid Aadhaar is masked and an invalid 12-digit number (an order id) isn't;
    - a PAN is masked;
    - phones in several formats normalise to the same digits;
    - a DOB is found only near its label;
    - masking twice changes nothing;
  - implement;
  - commit `feat(documents): find and mask Aadhaar, PAN and other personal data`.

### Task 3: Per-page text, hidden text and injection flags

**Interfaces:**
- **`text.extract(data, kind) -> ExtractedText(text, pages, page_texts, hidden)`** (extends SP-04a):
  - PDF: characters that are white or near-white (fill ≥ 0.9 on every channel), smaller than 3 pt or outside the page box are left out and collected in `hidden`;
  - DOCX: runs that are hidden (`vanish`), white or under 3 pt are left out the same way;
  - `page_texts` lists each page's visible text.
- **`hidden.inspect(extracted, metadata) -> SafetyFlags`:**
  - `hidden_text` (characters left out, with a 200-character sample);
  - `zero_width` (from `sections.normalise`);
  - `metadata_text` (PDF title, subject or keywords over 200 characters);
  - `injection`: phrases matched in the visible or hidden text, such as "ignore (all|any|the|previous) instructions", "disregard … above", "you are (now )?(an?|the) (ai|assistant|model)", "system prompt", "rank (me|this candidate) (first|highest|top)" or "score (me|this) (10|100)".
- **`text.needs_ocr(page_texts)`:** the page numbers with under 20 visible characters.

- [ ] **Steps:**
  - failing tests (`tests/test_documents_safety.py`, building PDFs with white and 1-pt text and DOCX files with hidden runs):
    - hidden text is left out of the text and reported;
    - an injection phrase in white text is flagged;
    - ordinary text raises no flag;
    - a scanned-looking (empty) page is reported as needing OCR;
  - implement;
  - commit `feat(documents): leave out and flag hidden text and injection attempts`.

### Task 4: OCR and ZIP archives

**Interfaces:**
- **`ocr.read(services.ai, organization_id, data, kind, pages: list[int] | None) -> OcrText(page_texts, confidence)`:**
  - images (PNG, JPEG, TIFF with every frame) are read page by page with `ai.ocr.read_page` (purpose `resume.ocr`);
  - scanned PDF pages are rendered by pypdfium2 at 200 dpi to PNG first;
  - images over 25 megapixels are rejected (`image-too-large`);
  - a mean confidence under 0.6 sets the `low_ocr_confidence` flag.
- **`archive.entries(data) -> list[ArchiveEntry(name, data)]`** raises `DocumentRejected`:
  - `archive-too-large` (over 200 entries, or over 200 MB uncompressed);
  - `archive-bomb` (an entry's ratio over 100);
  - `unreadable`.
  - It skips directories, hidden files (`__MACOSX/`, dotfiles), nested archives and unsupported types, and reports each skip with its reason. It reads with size-bounded streams and never writes to disk.

- [ ] **Steps:**
  - failing tests:
    - a PNG resume and a PDF with one image-only page are read through the mock OCR;
    - a TIFF with two frames gives two pages;
    - a 30-megapixel image is refused;
    - a ZIP of three resumes gives three entries;
    - a ZIP bomb, a nested ZIP and too many entries are handled as specified;
  - implement;
  - commit `feat(documents): read images and scanned pages, and open ZIP archives`.

### Task 5: The resume parse

**Interfaces** (`documents.resume`):
- **`ResumeExtraction`** (pydantic): each item carries a `quote`, and contact fields carry their own:
  - `name`, `email`, `phone`, `location`, `summary`;
  - `skills[{name, years, quote}]`;
  - `total_experience_years`;
  - `positions[{company, title, start, end, current, quote}]`: companies, job titles and employment dates;
  - `education[{institution, degree, field, start, end, quote}]`;
  - `certifications[{name, issuer, year, quote}]`;
  - `projects[{name, description, quote}]`;
  - `achievements[{text, quote}]`;
  - `languages[{name, quote}]`;
  - `links[{url, quote}]`.
- **`async def parse_resume(llm, organization_id, text, page_texts, sections, *, document_id) -> ResumeResult(extraction, evidence, dropped, model)`:**
  - one `complete` call (purpose `resume.parse`, prompt `resume-parse-v1`, tier `strong`) on the masked visible text, at most 40,000 characters;
  - quotes are verified with `quotes.verified`, and unverified items are dropped;
  - `email` and `phone` must also match `pii.find` results in the text;
  - `evidence` maps every kept item to `{page, section, quote}`: the page found from `page_texts`, the section from `sections.detect`.

- [ ] **Steps:**
  - failing tests (`tests/test_resume_parse.py`, with a scripted mock LLM):
    - a made-up company is dropped and counted;
    - an email that isn't in the text is dropped;
    - evidence gives the right page and section;
    - the text sent to the AI holds no raw Aadhaar;
  - implement, with the prompt file;
  - commit `feat(documents): parse resumes into evidence-backed profiles`.

### Task 6: Candidates: de-duplication, profiles and applications

**Interfaces** (`hirevion_core.candidates`):
- **`dedupe.match(session, *, email, phone, name, sha256) -> Match(candidate | None, reason, possible_duplicate_of)`** tries, in order:
  1. the same email (case-insensitive);
  2. the same normalised phone;
  3. a resume with the same SHA-256 already parsed in the organisation;
  4. a name with trigram similarity ≥ 0.92 whose candidate has no conflicting email or phone (a conflicting one only sets `possible_duplicate_of`).
- **`profiles.build(session, actor_or_system, document, result) -> Candidate`:**
  - creates or updates the candidate (`candidate.created` or `candidate.merged`);
  - replaces its skills (normalised with `resolve_skills`, carrying years);
  - sets `profile`, `flags` and the embedding (purpose `resume.embed`, from name-free profile text);
  - creates the application for the document's job (stage `parsed`) unless one exists.
- **`candidates.candidates_statement(scope, filters)`, `get_candidate(session, id, scope)`, `applications_statement(job_id, filters)`:** scope goes through applications and jobs.

- [ ] **Steps:**
  - failing tests (database):
    - two resumes with one email make one candidate with two documents;
    - a phone written differently matches;
    - the same file uploaded to another job reuses the candidate without a second AI call;
    - a near-identical name with a different email is a new candidate flagged as a possible duplicate;
    - a team-limited user sees only candidates of jobs they reach;
  - implement;
  - commit `feat(candidates): build de-duplicated candidates and their applications`.

### Task 7: Intake and the pipeline's resume and archive branches

**Interfaces:**
- **`intake.submit_resume_file(session, actor, job_id, data, filename, blobs) -> Document`:**
  - accepts PDF, DOCX, TXT, PNG, JPEG, TIFF (10 MB) and ZIP (50 MB, kind `archive`);
  - audits `resume.uploaded`;
  - queues the document.
- **`pipeline.process_document`** branches on kind:
  - **`archive`:** scan → `archive.entries` → a child `resume` document per entry (blob `jobs/{job}/resumes/{id}.{ext}`, `parent_id`, original name) → each child queued → the archive ends `parsed` with `flags.entries` and `flags.skipped`;
  - **`resume`:**
    1. a file whose SHA-256 was already parsed reuses that result (step 3 of `match`);
    2. otherwise: scan → text → OCR for images and pages that need it (status `ocr`) → safety flags → mask → `parse_resume` → `profiles.build`;
    3. the document stores the masked visible text and the extraction with evidence, and ends `parsed` with `candidate_id`;
    4. AI or OCR failures follow SP-04a's rules (retry or `failed` with a reason).
- **The upload body limit** becomes per route: 11 MiB for `/jd`, 51 MiB for `/resumes`.

- [ ] **Steps:**
  - failing tests (database, mock AI with scripted `resume.parse` and `resume.ocr`, fake scanner):
    - a PDF resume ends `parsed` with a candidate and an application;
    - a ZIP of two resumes and an EICAR file gives two candidates and one quarantined child;
    - an image resume goes through `ocr`;
    - an injection sample is parsed and flagged on the candidate;
    - no raw Aadhaar is stored, which a query checks over `documents` and `candidates`;
  - implement;
  - commit `feat(documents): process resumes and ZIP uploads into candidates`.

### Task 8: The API

**Routes** (creates take `Idempotency-Key`):
- `POST /api/v1/jobs/{job_id}/resumes` (`candidates.manage`): multipart `file`; 202 with the document. This is the PRD §90 example endpoint.
- `GET /api/v1/jobs/{job_id}/resumes` (`candidates.view`):
  - the job's resume and archive documents, newest first, paged;
  - filters: `status`, and `parent_id` (an archive's entries);
  - each item has its status, error, flags summary and candidate (id, name).
- `GET /api/v1/jobs/{job_id}/applications` (`candidates.view`): the job's candidates (name, headline, location, top skills, flags, stage, applied), paged, with search.
- `GET /api/v1/candidates` (`candidates.view`): search (`q` on name, email or phone), `job_id`, paged, scoped.
- `GET /api/v1/candidates/{candidate_id}` (`candidates.view`): profile with evidence, skills, applications (job reference, title and stage), resume documents and flags.
- `GET /api/v1/documents/{document_id}/download` (`candidates.view` for resumes, `jobs.view` for job descriptions):
  - 307 to a 5-minute signed URL;
  - audits `candidate.resume_downloaded` for resumes;
  - 409 `quarantined` for a quarantined file.
- **Retry:** `POST /documents/{id}/retry` also accepts resumes (`candidates.manage`).

- [ ] **Steps:**
  - failing API tests for each route's success and main refusals;
  - add the rows to the matrix's EXPECTED table;
  - implement;
  - run `hv openapi` and codegen;
  - commit `feat(api): add resume upload, candidates and applications`.

### Task 9: Web

- **Job page:**
  - **Resumes tab:**
    - a drop zone and file picker for many files or a ZIP;
    - each file is sent in its own request, three at a time, with per-file progress and its own idempotency key;
    - a processing list that polls every 2 s while anything is unfinished, showing each document's status, its candidate link, flags (hidden text, injection, low OCR confidence, possible duplicate), and Retry when failed;
    - a quarantine notice;
    - an archive's entries are nested under it.
  - **Candidates tab:** the job's applications, with search.
- **`/candidates`:** the list, with search and a job filter. The stage tabs stay as SP-03 built them; SP-05 drives stages.
- **`/candidates/[id]`** (a `detail` route):
  - **Profile:** contact, summary, skills with years, positions, education, certifications, projects, achievements, languages and links, each with "From the resume, page N: “…”";
  - **Resume:** the documents, with download;
  - the flags shown as warnings;
  - the applications.
- **Development sessions** see the admin notice.

- [ ] **Steps:**
  - failing component tests:
    - uploads go one request per file and show progress;
    - polling stops when everything is final;
    - a failed document offers Retry;
    - the profile shows evidence;
    - flags are announced;
  - implement;
  - commit `feat(web): upload resumes and show candidates`.

### Task 10: Synthetic resumes, the F1 evaluation and the exit criteria

- **`hv synth-resumes --count 200 --seed 7 --out tools/devcli/.cache/resumes`** writes the files plus `truth.jsonl` (the true value of every field):
  - **Fakes:** Faker en-IN people with fake employers, schools and skills from the taxonomy.
  - **Formats:** single-column and two-column PDFs with tables (reportlab), DOCX, TXT, PNG, JPG and TIFF, and scanned PDFs (an image inside a PDF).
  - **India-typical "Personal Details" blocks:** father's name, DOB, marital status, Aadhaar (Verhoeff-valid, synthetic) and PAN.
  - **Ten injection samples:** white and tiny text, and metadata.
  - **One EICAR file and one ZIP bundle.**
  - Generated files aren't committed (`.cache` is ignored).
- **`hv eval-resumes --dir … [--limit N]`:**
  1. creates an evaluation organisation and job, uploads every file through `intake`, and runs `process_document` in-process, four at a time, with the configured AI profile;
  2. scores each field against the truth:
     - exact match for email and phone after normalisation;
     - rapidfuzz token-sort ≥ 90 for text;
     - set matching for lists;
  3. reports precision, recall and F1 per field and overall;
  4. checks the exit criteria:
     - all 200 processed;
     - EICAR quarantined;
     - every injection sample flagged;
     - no raw Aadhaar in `documents` or `candidates`;
  5. writes `docs/evals/2026-10-resume-parse.md`.
- **Targets:** overall F1 ≥ 0.90; name, email and phone ≥ 0.95. If they're missed, adjust the prompt (as `resume-parse-v2`) or the OCR settings and run again; the report records each run.
- **Playwright (real API, mock AI with scripted `resume.parse`):** a recruiter uploads two resumes on a job's Resumes tab, waits for `parsed`, opens a candidate and sees evidence. Includes axe checks.
- **Docs:**
  - ADR-0015 amendment: de-duplication rules, OCR, and the measured F1;
  - runbook: resumes, ZIP limits, the synthetic set and the evaluation;
  - master plan Appendix A §13, §14 and §19, with SP-04 marked delivered.
- **Full gate:** both Playwright modes, then push, CI green, merge to `main`, update memory.

- [ ] **Steps:** generator and scorer unit tests first (deterministic seed, the F1 arithmetic), then the live run, then the e2e and docs. Commit as `feat(devcli): …`, `test(e2e): …` and `docs: …`.
