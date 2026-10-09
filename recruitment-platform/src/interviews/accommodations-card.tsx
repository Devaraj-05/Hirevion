"use client";

import {
  Badge,
  type BadgeTone,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Checkbox,
  Label,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { interviewKeys } from "./assigned-api";
import {
  ACCOMMODATION_KINDS,
  type Accommodation,
  type AccommodationKind,
  decideAccommodation,
  listAccommodations,
  sessionKeys,
} from "./session-api";

function isKind(kind: string): kind is AccommodationKind {
  return (ACCOMMODATION_KINDS as readonly string[]).includes(kind);
}

/** A kind's label; one this app doesn't know yet shows as the API wrote it. */
function useKindLabel(): (kind: string) => string {
  const t = useTranslations("interviews.session.accommodations");
  return (kind) => (isKind(kind) ? t(`kinds.${kind}`) : kind);
}

const STATUS_TONES: Record<Accommodation["status"], BadgeTone> = {
  requested: "warning",
  approved: "success",
  declined: "neutral",
};

function Decision({
  interviewId,
  request,
  onDecided,
}: {
  interviewId: string;
  request: Accommodation;
  onDecided: () => void;
}) {
  const t = useTranslations("interviews.session.accommodations");
  const label = useKindLabel();
  const problems = useAdminProblem();
  const id = useId();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(request.kinds));
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (approved: string[]) =>
      decideAccommodation(interviewId, request.id, approved, note.trim() || null),
    onSuccess: (saved) => {
      toast.success(saved.status === "approved" ? t("approved") : t("declined"), {});
      onDecided();
    },
    onError: problems.show,
  });
  const toggle = (kind: string) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  return (
    <div className="grid gap-3">
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm">{t("chooseApproved")}</legend>
        {request.kinds.map((kind) => (
          <div key={kind} className="flex items-center gap-2">
            <Checkbox
              id={`${id}-${kind}`}
              checked={chosen.has(kind)}
              onCheckedChange={() => toggle(kind)}
            />
            <Label htmlFor={`${id}-${kind}`}>{label(kind)}</Label>
          </div>
        ))}
      </fieldset>
      <div className="grid gap-1">
        <Label htmlFor={`${id}-note`}>{t("note")}</Label>
        <Textarea
          id={`${id}-note`}
          value={note}
          maxLength={2000}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={decide.isPending || chosen.size === 0}
          onClick={() => decide.mutate(request.kinds.filter((kind) => chosen.has(kind)))}
        >
          {t("approve")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={decide.isPending}
          onClick={() => decide.mutate([])}
        >
          {t("decline")}
        </Button>
      </div>
    </div>
  );
}

/** The candidate's accommodation requests; with `canDecide` (before the interview starts) a
 * recruiter approves some or all of them, which changes the interview's answer mode, time,
 * breaks or third-eye requirement. */
export function AccommodationsCard({ id, canDecide }: { id: string; canDecide: boolean }) {
  const t = useTranslations("interviews.session.accommodations");
  const label = useKindLabel();
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: sessionKeys.accommodations(id),
    queryFn: () => listAccommodations(id),
  });
  const decided = () => {
    void queryClient.invalidateQueries({ queryKey: sessionKeys.accommodations(id) });
    void queryClient.invalidateQueries({ queryKey: interviewKeys.detail(id) });
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {requests.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : requests.isError ? (
          <p className="text-sm" role="alert">
            {t("loadFailed")}
          </p>
        ) : requests.data.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="grid gap-4">
            {requests.data.map((request) => (
              <li key={request.id} className="grid gap-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={STATUS_TONES[request.status]}>
                    {t(`statuses.${request.status}`)}
                  </Badge>
                  {request.kinds.map((kind) => (
                    <Badge key={kind}>{label(kind)}</Badge>
                  ))}
                </div>
                {request.note ? (
                  <p className="text-muted-foreground">
                    {t("candidateNote", { note: request.note })}
                  </p>
                ) : null}
                {request.status === "approved" ? (
                  <p>
                    {t("approvedKinds", {
                      kinds: request.approved_kinds.map((kind) => label(kind)).join(", "),
                    })}
                  </p>
                ) : null}
                {request.status === "requested" && canDecide ? (
                  <Decision interviewId={id} request={request} onDecided={decided} />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
