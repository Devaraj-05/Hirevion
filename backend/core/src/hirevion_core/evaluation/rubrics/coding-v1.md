Score anchors (every criterion, 0 to 10):

- 0: no attempt at the question, or code that does something else entirely.
- 2: an attempt, but the logic is mostly wrong or missing.
- 5: partly right; the main idea is there, with gaps or errors that matter.
- 8: sound and fairly complete, the code of a competent practitioner.
- 10: correct, complete and well judged, with the care a senior practitioner would take.

Use the whole range. Do not cluster scores around the middle, and do not give a high score for
length, comments or confident naming alone.

The seven criteria:

- correctness: whether the logic, traced by hand, gives the right result for the question's
  ordinary inputs.
- approach: whether the chosen method (data structures, algorithm, query shape) suits the problem
  and its likely size.
- edge_cases: whether the code considers the awkward inputs (empty, single item, duplicates, no
  answer, nulls, limits) and handles them sensibly.
- time_complexity: how appropriate the estimated running time is for the question; a needlessly
  slower method scores lower.
- space_complexity: how appropriate the estimated extra memory is for the question.
- code_quality: structure, decomposition and sound use of the language: no dead code, no
  needless repetition, no unsafe shortcuts.
- readability: whether another engineer could follow it quickly: names, layout, and comments
  where the intent isn't obvious.
