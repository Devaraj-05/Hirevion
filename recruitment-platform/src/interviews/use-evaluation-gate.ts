"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { evaluationKeys, getEvaluation, listMyScores } from "./evaluation-api";
import { summaryRevealed } from "./evaluation-model";

/**
 * Whether the AI's numbers may be shown to this reviewer yet (ADR-0031): once they have saved a
 * score for every question, so the AI's don't set theirs, or when they choose to skip scoring.
 * Every panel that shows the AI's scores reads this, so none gives away what the evaluation card
 * is still holding back. The queries are the evaluation card's own, shared through the cache.
 */
export function useEvaluationGate(id: string) {
  const queryClient = useQueryClient();
  const evaluation = useQuery({
    queryKey: evaluationKeys.detail(id),
    queryFn: () => getEvaluation(id),
  });
  const mine = useQuery({ queryKey: evaluationKeys.mine(id), queryFn: () => listMyScores(id) });
  const waived = useQuery({
    queryKey: evaluationKeys.waived(id),
    queryFn: () => false,
    initialData: false,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });
  const questions = evaluation.data?.evaluation?.questions ?? [];
  const scored = new Set((mine.data ?? []).map((row) => row.question_id));
  const progress = {
    saved: questions.filter((question) => scored.has(question.question_id)).length,
    total: questions.length,
  };
  const waive = useCallback(() => {
    queryClient.setQueryData(evaluationKeys.waived(id), true);
  }, [queryClient, id]);
  return {
    /** The saved scores are known, and the reviewer has scored everything or chosen to skip. */
    revealed: evaluation.isSuccess && mine.isSuccess && summaryRevealed(progress, waived.data),
    /** The evaluation and the reviewer's scores have loaded (or failed to). */
    loaded: !evaluation.isPending && !mine.isPending,
    failed: mine.isError,
    progress,
    waive,
  };
}
