"use client";

import { isApiProblem } from "@hirevion/api-client";
import { Badge, type BadgeTone, Button, Skeleton } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type DragEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { listResumes, type ResumeDocument, uploadResume } from "@/candidates/api";
import { FlagBadges } from "@/candidates/flags";
import { keys } from "@/candidates/queries";
import { retryDocument } from "./api";

const POLL_MS = 2_000;
const PARALLEL = 3;
const LIST_SIZE = 100;
const ACCEPT = ".pdf,.docx,.txt,.jpg,.jpeg,.png,.tif,.tiff,.zip";
const FINAL = new Set(["parsed", "quarantined", "failed"]);
const ERRORS = [
  "unreadable",
  "too-many-pages",
  "no-text",
  "ai-failed",
  "ocr-failed",
  "budget-exceeded",
  "retries-exhausted",
  "image-too-large",
  "archive-too-large",
  "archive-bomb",
] as const;
const TONES: Record<string, BadgeTone> = {
  parsed: "success",
  failed: "warning",
  quarantined: "danger",
};

interface Sending {
  id: string;
  name: string;
  state: "queued" | "uploading" | "sent" | "failed";
  reason?: string;
}

/** A job's resumes (PRD §13): send files or a ZIP, then follow each one being read. */
export function ResumesPanel({
  jobId,
  canUpload,
  pollMs = POLL_MS,
}: {
  jobId: string;
  canUpload: boolean;
  pollMs?: number;
}) {
  const t = useTranslations("jobs.resumes");
  const errors = useTranslations("jobs.description.errors");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const inputId = useId();
  const [uploads, setUploads] = useState<Sending[]>([]);
  const [dragging, setDragging] = useState(false);

  const resumes = useQuery({
    queryKey: keys.resumes(jobId),
    queryFn: () => listResumes(jobId, { limit: LIST_SIZE }),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => !FINAL.has(item.status)) ? pollMs : false,
  });

  const retry = useMutation({
    mutationFn: (document: ResumeDocument) => retryDocument(document.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.resumes(jobId) }),
    onError: problems.show,
  });

  function update(id: string, changes: Partial<Sending>) {
    setUploads((previous) =>
      previous.map((upload) => (upload.id === id ? { ...upload, ...changes } : upload)),
    );
  }

  async function send(files: File[]) {
    const queued = files.map((file) => ({
      id: crypto.randomUUID(),
      key: crypto.randomUUID(),
      file,
    }));
    setUploads((previous) => [
      ...queued.map(({ id, file }) => ({ id, name: file.name, state: "queued" as const })),
      ...previous,
    ]);
    let next = 0;
    async function worker() {
      while (next < queued.length) {
        const item = queued[next++];
        if (!item) return;
        update(item.id, { state: "uploading" });
        try {
          await uploadResume(jobId, item.file, item.key);
          update(item.id, { state: "sent" });
        } catch (error) {
          const reason = isApiProblem(error) ? (error.detail ?? error.title) : String(error);
          update(item.id, { state: "failed", reason });
        }
        void queryClient.invalidateQueries({ queryKey: keys.resumes(jobId) });
      }
    }
    await Promise.all(Array.from({ length: Math.min(PARALLEL, queued.length) }, worker));
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (canUpload && event.dataTransfer.files.length > 0) {
      void send([...event.dataTransfer.files]);
    }
  }

  const items = resumes.data?.items ?? [];
  const children = new Map<string, ResumeDocument[]>();
  for (const item of items) {
    if (item.parent_id)
      children.set(item.parent_id, [...(children.get(item.parent_id) ?? []), item]);
  }
  const shownParents = new Set(items.map((item) => item.id));
  const top = items.filter((item) => !item.parent_id || !shownParents.has(item.parent_id));

  function status(document: ResumeDocument) {
    if (document.status === "failed") {
      const code = (ERRORS as readonly string[]).includes(document.error_code ?? "")
        ? (document.error_code as (typeof ERRORS)[number])
        : "unknown";
      return t("failedReason", { reason: errors(code) });
    }
    return t(`statuses.${document.status}`);
  }

  function row(document: ResumeDocument, nested: boolean) {
    const entries =
      document.kind === "archive" ? (document.flags.entries as number | undefined) : undefined;
    const skipped = (document.flags.skipped as { name: string }[] | undefined) ?? [];
    return (
      <tr key={document.id} className="border-border border-t align-top">
        <td className={nested ? "py-2 pr-3 pl-8" : "px-3 py-2"}>
          <div className="font-medium">{document.filename ?? "—"}</div>
          {entries !== undefined ? (
            <div className="text-muted-foreground text-xs">{t("entries", { count: entries })}</div>
          ) : null}
          {skipped.length > 0 ? (
            <div className="text-muted-foreground text-xs">
              {t("skipped", { names: skipped.map((skip) => skip.name).join(", ") })}
            </div>
          ) : null}
        </td>
        <td className="px-3 py-2">
          <Badge tone={TONES[document.status] ?? "neutral"}>{status(document)}</Badge>
          {document.status === "quarantined" ? (
            <div className="text-danger text-xs">{t("quarantinedHint")}</div>
          ) : null}
        </td>
        <td className="px-3 py-2">
          <div className="grid gap-1">
            {document.candidate ? (
              <Link href={`/candidates/${document.candidate.id}`} className="hover:underline">
                {document.candidate.name}
              </Link>
            ) : (
              "—"
            )}
            <FlagBadges flags={document.flags} />
          </div>
        </td>
        <td className="px-3 py-2">
          {format.dateTime(new Date(document.created_at), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </td>
        <td className="px-3 py-2 text-right">
          {canUpload && document.status === "failed" ? (
            <Button
              size="sm"
              variant="secondary"
              aria-label={t("retryNamed", { name: document.filename ?? "" })}
              disabled={retry.isPending}
              onClick={() => retry.mutate(document)}
            >
              {t("retry")}
            </Button>
          ) : null}
        </td>
      </tr>
    );
  }

  return (
    <div className="grid gap-4">
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      {canUpload ? (
        <section
          aria-label={t("dropZone")}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`grid justify-items-center gap-2 rounded-lg border-2 border-dashed p-6 ${
            dragging ? "border-accent bg-accent-subtle" : "border-border"
          }`}
        >
          <Upload className="size-6 text-muted-foreground" aria-hidden />
          <label
            htmlFor={inputId}
            className="cursor-pointer rounded-md bg-accent px-3 py-2 font-medium text-accent-foreground text-sm"
          >
            {t("choose")}
          </label>
          <input
            id={inputId}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => {
              const files = [...(event.target.files ?? [])];
              event.target.value = "";
              if (files.length > 0) void send(files);
            }}
          />
          <span className="text-muted-foreground text-xs">{t("drop")}</span>
        </section>
      ) : (
        <p className="text-muted-foreground text-sm">{t("readOnly")}</p>
      )}
      {uploads.length > 0 ? (
        <section aria-label={t("uploads")} className="grid gap-1">
          <h3 className="font-medium text-sm">{t("uploads")}</h3>
          <ul className="grid gap-1 text-sm" aria-live="polite">
            {uploads.map((upload) => (
              <li key={upload.id} className="flex flex-wrap justify-between gap-2">
                <span>{upload.name}</span>
                <span
                  className={upload.state === "failed" ? "text-danger" : "text-muted-foreground"}
                >
                  {upload.state === "failed"
                    ? t("failedUpload", { reason: upload.reason ?? "" })
                    : t(upload.state)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {resumes.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("caption")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("file")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("status")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("candidate")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("uploaded")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">{t("retry")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {top.flatMap((document) => [
                row(document, false),
                ...(children.get(document.id) ?? []).map((child) => row(child, true)),
              ])}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
