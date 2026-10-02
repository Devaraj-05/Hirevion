# SP-04 Jobs and documents: design

- **Date:** 2026-10-02
- **Status:** Approved by the product owner on 2026-10-02
  - Split into SP-04a and SP-04b.
  - Background work on Valkey-stream consumers.
  - Built-in PII recognisers.
  - Extraction F1 ≥ 0.90.
- **Master plan:** §14 SP-04, §6.6, D2. **PRD:** §11–§14, §19, §81, §97.

## Goal

Jobs with the PRD's fields and lifecycle, and the two document pipelines feeding screening (SP-05):
- job descriptions become an editable, versioned screening profile;
- resumes become candidates with an evidence-backed parsed profile.

## Delivery: two parts

- **SP-04a, jobs and job descriptions:**
  - **Jobs:** PRD §11's fields, five statuses, versions, recruiter and hiring-manager assignment, and the owning team (for ADR-0014's scope).
  - **JD input:** upload (PDF, DOCX, TXT) or pasted text.
  - **The JD pipeline:**
    1. validate;
    2. virus scan;
    3. extract text;
    4. normalise;
    5. detect sections;
    6. extract role, skills, requirements and experience, with verified quotes;
    7. embed;
    8. build the screening profile.
  - **Review:** the recruiter reviews and edits the extraction before applying it to the job.
  - **Supporting pieces:**
    - the skills taxonomy;
    - the documents table and its background consumer;
    - processing status with retry;
    - the jobs pages.
- **SP-04b, resumes and candidates:**
  - **Upload:** single, bulk and ZIP; PDF, DOCX, TXT, JPG, PNG and TIFF.
  - **Checks:** validation and ZIP limits; ClamAV with quarantine.
  - **Text:** extraction, with OCR for images and scanned PDFs.
  - **Safety:** hidden-text and injection flags; Aadhaar and PAN masking.
  - **The AI parse:** PRD §14's 16 fields, each with a page, section and quote checked against the text.
  - **Candidates:** candidates and applications, de-duplicated by email, phone, fuzzy name or file hash, with skills normalised to the taxonomy.
  - **Embeddings.**
  - **The processing-status UI** with retries.
  - **Test data:** 200 synthetic resumes with known true values, and an F1 evaluation.
  - Its plan is written after SP-04a merges.

## Decisions

- **Background work.** Valkey-stream consumers replace the master plan's Celery worker (D2):
  - **The flow:** a change writes an outbox event in its own transaction; the relay publishes it; a `documents` consumer processes it.
  - **Delivery:** retries, a dead-letter stream after five deliveries, and de-duplication by event id. It is the same pattern the mail consumer uses.
  - **Where it runs:** inside the API (`HV_API_RUN_WORKERS`) or as `hv worker`.
  - **Recorded** in ADR-0015 and in master plan §2.
- **PII.**
  - **Built-in recognisers:** Aadhaar (12 digits, Verhoeff checksum), PAN, phone numbers, email addresses and dates of birth.
  - **Aadhaar and PAN** are masked (only the last four characters kept) before text is stored or sent to an AI service.
  - **SP-05's blind mode** redacts names, gender and age from the parsed fields.
  - **Presidio is not used.**
- **Extraction accuracy.** Field-level F1 ≥ 0.90 overall, and ≥ 0.95 for name, email and phone. It is measured live (Gemini) on the synthetic set in SP-04b, which sets the target the master plan expected from SP-00.
- **Documents.**
  - **One `documents` table** serves job descriptions and resumes.
  - **Columns:** kind, file name, content type, size, SHA-256, blob path, status, error code, attempts, extracted (masked) text, page count, flags and extraction.
  - **Statuses:** `uploaded` → `scanning` → `extracting` → `parsing` → `parsed`, or `quarantined` / `failed`.
  - **Files** live in blob storage under ADR-0011's paths.
  - **A retry** re-queues a failed document.
- **Job fields.**
  - **Columns:**
    - title, department, team;
    - location and work model;
    - employment type;
    - minimum and maximum years of experience;
    - description;
    - responsibilities, qualifications and domain;
    - salary (optional);
    - hiring manager and recruiter;
    - status.
  - **Skills** are rows in `job_skills`: required, preferred or optional, linked to the taxonomy when known.
  - **"Job ID"** is a per-organisation number shown as `JOB-0042`.
  - **"Screening Configuration"** arrives with SP-05 and **"Interview Template"** with SP-06; Appendix A says so.
- **Lifecycle.**
  - **Transitions:** Draft → Open; Open ⇄ Paused; Open or Paused → Closed; Closed → Archived.
  - **Every change** to the job's fields, skills or status writes a `job_versions` snapshot and an audit entry ("Job created/changed", "JD uploaded/changed").
- **The skills taxonomy.**
  - **Shared by all organisations,** seeded by migration: about 250 common skills with their aliases (`js` → JavaScript).
  - **Skills the taxonomy doesn't know** stay as free text on the job.
- **The JD extraction.**
  - **One structured LLM call** (purpose `jd.extract`, prompt version `jd-extract-v1`) returns: title, required and preferred skills, minimum and maximum years, responsibilities, qualifications, domain, location and work model.
  - **Each item comes with a quote.** Quotes not found in the text (after normalisation) are dropped and counted.
  - **The extraction is stored on the document.** "Apply" writes the recruiter-edited version to the job.
  - **The job's embedding** (1536 dimensions, pgvector) is computed from the applied profile.
- **Scope.** Jobs belong to a team and a recruiter, so `scope_clause(Job.team_id, Job.recruiter_id)` limits team-limited users (ADR-0014).
- **Permissions.**
  - `jobs.view` reads.
  - `jobs.create` creates and edits jobs and their descriptions; its label becomes "Create and edit jobs".

## Testing

- **Unit:**
  - validation (magic bytes, size);
  - text extraction per format;
  - normalisation and section detection;
  - quote verification;
  - taxonomy normalisation;
  - the status machine;
  - the Verhoeff and PAN recognisers (SP-04b).
- **Database:**
  - jobs, skills, versions and documents are tenant-isolated;
  - the pipeline runs end to end with a scripted mock LLM and a fake scanner;
  - an infected file is quarantined;
  - a retry re-runs a failed document;
  - scope filtering.
- **API:** every route in the authorisation matrix; job CRUD, status changes, JD upload and paste, extraction apply, versions, retry.
- **Web:** component tests for the list, the form and the review screen; Playwright (real API) creates a job, pastes a description, reviews and applies it.
