# Screening evaluation

- **Status:** pending a live run. `uv run hv eval-screening` overwrites this page with the results.
- **Target (ADR-0016):** mean NDCG@10 ≥ 0.80 over three role-family jobs (backend, frontend, data), with labels from each candidate's true skills.
- **Order:** it needs the synthetic set parsed by a real AI first:

```sh
uv run hv synth-resumes
uv run hv eval-resumes      # parses the 200 resumes with Gemini
uv run hv eval-screening    # screens 60 candidates for each of 3 jobs (180 AI calls)
```

With the mock AI, the evaluation refuses to run: the mock doesn't read resumes, so no candidate matches the truth set.
