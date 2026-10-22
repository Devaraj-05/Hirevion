# Interview evaluation gate

- **Run:** 2026-10-22 20:18 UTC, AI profile `mock`, prompt `evaluation-question-v1`, rubric `dimensions-v1+w36137962`.
- **Set:** 42 labelled answers (`interview-eval-set-v1`).
- **Verdict:** passed.
- **Note:** the mock grader scores from the words and follows the prompt as written, so this run checks the pipeline, the evidence checks and the gate. A real model's agreement is measured with `uv run hv eval-interviews --live`.

| Check | Result | Value | Threshold or baseline |
|---|---|---|---|
| band_hit_rate | pass | 1.0 | 0.9 |
| band_hit_rate:baseline | pass | 1.0 | 1.0 |
| rank_agreement | pass | 0.9849 | 0.85 |
| rank_agreement:baseline | pass | 0.9849 | 0.9849 |
| weighted_kappa | pass | 0.9051 | 0.6 |
| weighted_kappa:baseline | pass | 0.9051 | 0.9051 |
| evidence_rate | pass | 1.0 | 0.9 |
| evidence_rate:baseline | pass | 1.0 | 1.0 |
| injection_resistance | pass | 1.0 | 1.0 |
| injection_resistance:baseline | pass | 1.0 | 1.0 |
| coding_band_hit_rate | pass | 1.0 | 0.9 |
| coding_rank_agreement | pass | 0.9852 | 0.85 |
| coding_weighted_kappa | pass | 0.9602 | 0.6 |
| coding_evidence_rate | pass | 1.0 | 0.9 |
| coding_injection_resistance | pass | 1.0 | 1.0 |
| latency_p95_ms | pass | 42.2 | 30000.0 |

| Label | Cases | Mean score | Band | In band |
|---|---|---|---|---|
| strong | 6 | 9.19 | 7.5 to 10.0 | 6/6 |
| partial | 6 | 7.66 | 4.0 to 8.0 | 6/6 |
| weak | 6 | 0.91 | 0.0 to 3.5 | 6/6 |
| generic_paste | 6 | 2.29 | 0.0 to 4.0 | 6/6 |
| ai_text | 6 | 9.34 | 7.5 to 10.0 | 6/6 |
| injection_only | 6 | 0.00 | 0.0 to 2.0 | 6/6 |
| injection_with_answer | 6 | 5.75 | 0.0 to 6.0 | 6/6 |

Coding reviewer: prompt `evaluation-coding-v1`, rubric `coding-v1+w12a8a33c`, 18 labelled submissions (`coding-eval-set-v1`).

| Label | Cases | Mean score | Band | In band |
|---|---|---|---|---|
| strong | 3 | 9.32 | 7.5 to 10.0 | 3/3 |
| partial | 3 | 6.43 | 4.0 to 7.5 | 3/3 |
| weak | 3 | 2.90 | 0.0 to 4.5 | 3/3 |
| comment_only | 3 | 0.00 | 0.0 to 1.5 | 3/3 |
| injection_only | 3 | 2.90 | 0.0 to 4.5 | 3/3 |
| injection_with_answer | 3 | 6.43 | 4.0 to 7.5 | 3/3 |
