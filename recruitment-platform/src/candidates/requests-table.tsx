"use client";

import {
  Badge,
  type BadgeTone,
  Button,
  Dialog,
  DialogContent,
  EmptyState,
  Label,
  NativeSelect,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Inbox } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  type CandidateRequest,
  listCandidateRequests,
  REQUEST_STATUSES,
  type RequestStatus,
  requestKeys,
  updateCandidateRequest,
} from "./requests-api";

/** Candidates' requests from the portal (master plan §6.3; ADR-0022), for recruiters to act on:
 * each moves from received, through in progress, to resolved or declined, with a reply. */

const TONES: Record<RequestStatus, BadgeTone> = {
  open: "info",
  in_progress: "warning",
  resolved: "success",
  declined: "neutral",
};
const DETAIL_KEYS = [
  "preferred",
  "kinds",
  "purposes",
  "nominee_name",
  "nominee_email",
  "relationship",
  "field",
] as const;
const CLOSED = new Set<RequestStatus>(["resolved", "declined"]);

function detailText(value: unknown): string {
  return Array.isArray(value) ? value.map(String).join(", ") : String(value);
}

function UpdateDialog({ request, onClose }: { request: CandidateRequest; onClose: () => void }) {
  const t = useTranslations("candidateRequests");
  const portal = useTranslations("portal.requests");
  const shell = useTranslations("shell");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const [status, setStatus] = useState<"in_progress" | "resolved" | "declined">(
    request.status === "open" ? "in_progress" : "resolved",
  );
  const [response, setResponse] = useState(request.response ?? "");
  const save = useMutation({
    mutationFn: () =>
      updateCandidateRequest(request.id, { status, response: response.trim() || null }),
    onSuccess: () => {
      toast.success(t("saved"), {});
      void queryClient.invalidateQueries({ queryKey: requestKeys.all });
      onClose();
    },
    onError: problems.show,
  });
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent title={t("dialogTitle")} closeLabel={shell("close")}>
        <div className="grid gap-4 text-sm">
          <p className="text-muted-foreground">
            {[request.reference, request.candidate_name, portal(`kinds.${request.kind}`)].join(
              " · ",
            )}
          </p>
          {request.message ? (
            <div className="grid gap-1">
              <p className="font-medium">{t("message")}</p>
              <p className="whitespace-pre-wrap">{request.message}</p>
            </div>
          ) : null}
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
            {DETAIL_KEYS.filter((key) => request.details[key] !== undefined).map((key) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{t(`details.${key}`)}</dt>
                <dd>{detailText(request.details[key])}</dd>
              </div>
            ))}
          </dl>
          {request.kind === "accommodation" ? (
            <p className="text-muted-foreground">{t("adjustmentsOnInterview")}</p>
          ) : null}
          <div className="grid gap-1">
            <Label htmlFor={`${id}-status`}>{t("newStatus")}</Label>
            <NativeSelect
              id={`${id}-status`}
              value={status}
              onChange={(event) => setStatus(event.target.value as typeof status)}
              options={(["in_progress", "resolved", "declined"] as const).map((value) => ({
                value,
                label: portal(`status.${value}`),
              }))}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={`${id}-response`}>{t("response")}</Label>
            <Textarea
              id={`${id}-response`}
              value={response}
              maxLength={4000}
              aria-describedby={`${id}-response-hint`}
              onChange={(event) => setResponse(event.target.value)}
            />
            <p id={`${id}-response-hint`} className="text-muted-foreground text-xs">
              {t("responseHint")}
            </p>
          </div>
          <div>
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              {t("save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function CandidateRequestsTable({ canManage }: { canManage: boolean }) {
  const t = useTranslations("candidateRequests");
  const portal = useTranslations("portal.requests");
  const format = useFormatter();
  const id = useId();
  const [status, setStatus] = useState<RequestStatus | null>(null);
  const [editing, setEditing] = useState<CandidateRequest | null>(null);
  const query = useInfiniteQuery({
    queryKey: requestKeys.list(status),
    queryFn: ({ pageParam }) => listCandidateRequests(status, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="grid gap-4">
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      <div className="grid max-w-xs gap-1">
        <Label htmlFor={`${id}-status`}>{t("statusFilter")}</Label>
        <NativeSelect
          id={`${id}-status`}
          value={status ?? ""}
          onChange={(event) => setStatus((event.target.value || null) as RequestStatus | null)}
          options={[
            { value: "", label: t("allStatuses") },
            ...REQUEST_STATUSES.map((value) => ({ value, label: portal(`status.${value}`) })),
          ]}
        />
      </div>
      {query.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : query.isError ? (
        <p role="alert" className="text-sm">
          {t("loadFailed")}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState icon={<Inbox />} title={t("empty")} description={t("emptyHint")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("caption")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                {(
                  ["reference", "candidate", "kind", "interview", "received", "status"] as const
                ).map((column) => (
                  <th key={column} scope="col" className="p-2 font-medium">
                    {t(`columns.${column}`)}
                  </th>
                ))}
                {canManage ? (
                  <th scope="col" className="p-2 font-medium">
                    <span className="sr-only">{t("columns.actions")}</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-border border-t align-top">
                  <td className="p-2 font-mono text-xs">{row.reference}</td>
                  <td className="p-2">
                    <Link href={`/candidates/${row.candidate_id}`} className="hover:underline">
                      {row.candidate_name}
                    </Link>
                  </td>
                  <td className="p-2">{portal(`kinds.${row.kind}`)}</td>
                  <td className="p-2">
                    {row.interview_id && row.interview_reference ? (
                      <Link href={`/interviews/${row.interview_id}`} className="underline">
                        {row.interview_reference}
                      </Link>
                    ) : null}
                  </td>
                  <td className="p-2">
                    {format.dateTime(new Date(row.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </td>
                  <td className="p-2">
                    <Badge tone={TONES[row.status]}>{portal(`status.${row.status}`)}</Badge>
                  </td>
                  {canManage ? (
                    <td className="p-2">
                      {CLOSED.has(row.status) ? null : (
                        <Button
                          size="sm"
                          variant="secondary"
                          aria-label={t("update", { reference: row.reference })}
                          onClick={() => setEditing(row)}
                        >
                          {t("updateShort")}
                        </Button>
                      )}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.hasNextPage ? (
        <div>
          <Button
            variant="secondary"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {t("more")}
          </Button>
        </div>
      ) : null}
      {editing ? <UpdateDialog request={editing} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}
