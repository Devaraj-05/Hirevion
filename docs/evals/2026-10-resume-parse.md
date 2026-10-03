# Resume parsing evaluation

- **Status:** pending a live run. `uv run hv eval-resumes` overwrites this page with the results.
- **Targets (ADR-0015):** field F1 ≥ 0.90 overall, and ≥ 0.95 for name, email and phone.
- **Why it isn't measured yet:** on 2026-10-03, the `GEMINI_API_KEY` in `.env` was rejected by Google ("API key not valid").

## Checked with the mock AI (2026-10-03)

The pipeline, everything but the AI's answers, on the full synthetic set (`hv synth-resumes`, seed 7):

- **Processed:** 200 of 200 reached a final status (all `parsed`).
- **EICAR quarantined:** yes (ClamAV).
- **Injection samples flagged:** 10 of 10.
- **Raw Aadhaar numbers stored:** 0, in documents, candidates and AI records.
- **Exact copies reused without an AI call:** 10 (the ZIP bundle).

## How to run it

```sh
uv run hv synth-resumes            # 200 resumes and truth.jsonl in tools/devcli/.cache/resumes
uv run hv eval-resumes             # about 10 minutes and well under $1 with Gemini; writes this page
uv run hv eval-resumes --limit 20  # a quick look first
```
