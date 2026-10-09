"""The AI interview engine (PRD §33 to §43, master plan §6.8; SP-09).

A deterministic Python policy makes every decision; models only analyse answers and phrase some
follow-ups, never "one giant prompt" (§34). The nine §34 components, in the order they act:

1. `context.ContextBuilder`: resume evidence, the JD, the pinned template version, the library;
2. `skills.SkillMatrixBuilder`: weights, coverage targets, ladders and resume hooks per skill;
3. `planner.QuestionPlanner`: the question pool, each with its source (§36);
4. `analysis.AnswerAnalyzer`: correctness, completeness, depth, gaps, contradictions (§38);
5. `difficulty.DifficultyController` (§39);
6. `followups.FollowUpGenerator` (§38);
7. `coding.CodingController` (SP-16 adds the runs);
8. `timing.TimeController` (§40);
9. `completion.CompletionEvaluator` (§37 coverage).

`orchestrator.Orchestrator` steps the `state.InterviewState` (§34's twelve fields) through §35's
stages. Nothing here touches the database except the context builder, or the network except
the analyser and the follow-up phrasing.
"""
