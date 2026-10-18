"use client";

import { toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  changeHiringStatus,
  getPipeline,
  type HiringStatus,
  REASON_REQUIRED,
  reviewKeys,
} from "@/review/api";
import { MoveDialog } from "@/review/hiring-panel";
import type { PipelineCard, PipelineStatus } from "./model";
import { PipelineBoard } from "./pipeline-board";

interface Moving {
  card: PipelineCard;
  from: PipelineStatus;
  to: PipelineStatus;
  hasInterview: boolean;
}

/** The pipeline board on the live API (PRD §72): the nine columns with their counts, and moving a
 * card is the hiring-status change. A move that needs a reason, or is a decision, opens the
 * dialog that asks; the others happen at once. Every change is audited by the API. */
export function LivePipeline() {
  const t = useTranslations("hiring");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const [moving, setMoving] = useState<Moving | null>(null);
  const board = useQuery({ queryKey: reviewKeys.pipeline(), queryFn: () => getPipeline() });

  const { columns, counts, interviews } = useMemo(() => {
    const columns: Partial<Record<PipelineStatus, PipelineCard[]>> = {};
    const counts: Partial<Record<PipelineStatus, number>> = {};
    const interviews = new Map<string, boolean>();
    for (const column of board.data?.columns ?? []) {
      counts[column.status] = column.count;
      columns[column.status] = column.cards.map((card) => {
        interviews.set(card.application_id, card.interview_id !== null);
        return {
          id: card.application_id,
          name: card.candidate_name,
          job: card.job_title,
          href: `/candidates/${card.candidate_id}`,
          moves: card.moves,
        };
      });
    }
    return { columns, counts, interviews };
  }, [board.data]);

  function refreshed() {
    void queryClient.invalidateQueries({ queryKey: ["review", "pipeline"] });
    void queryClient.invalidateQueries({ queryKey: reviewKeys.pending });
  }
  const direct = useMutation({
    mutationFn: ({ card, to }: { card: PipelineCard; to: HiringStatus }) =>
      changeHiringStatus(card.id, { status: to, reason: null }),
    onSuccess: (next) => {
      toast.success(t("moved", { status: t(`statuses.${next.status}`) }), {});
      refreshed();
    },
    onError: problems.show,
  });

  function onMove(card: PipelineCard, to: PipelineStatus) {
    const from = (Object.keys(columns) as PipelineStatus[]).find((status) =>
      columns[status]?.some((candidate) => candidate.id === card.id),
    );
    if (!from) return;
    if (REASON_REQUIRED.includes(to)) {
      setMoving({ card, from, to, hasInterview: interviews.get(card.id) ?? false });
    } else {
      direct.mutate({ card, to });
    }
  }

  if (board.isPending) return null;
  if (board.isError) return null;
  return (
    <>
      <PipelineBoard columns={columns} counts={counts} onMove={onMove} />
      {moving ? (
        <MoveDialog
          applicationId={moving.card.id}
          state={{
            status: moving.from,
            allowed: [...(moving.card.moves ?? [])],
            has_interview: moving.hasInterview,
          }}
          initial={moving.to}
          onClose={() => setMoving(null)}
          onMoved={() => {
            setMoving(null);
            refreshed();
          }}
        />
      ) : null}
    </>
  );
}
