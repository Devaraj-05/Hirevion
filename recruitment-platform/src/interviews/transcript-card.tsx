"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@hirevion/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import {
  getTranscript,
  type LiveEvent,
  liveEventsUrl,
  sessionKeys,
  type TranscriptQuestion,
} from "./session-api";

const RECONNECT_MS = 3000;
const SOURCES = ["pinned", "library", "generated", "resume", "follow_up", "faq", "system"] as const;
type Source = (typeof SOURCES)[number];
const isSource = (value: string): value is Source => (SOURCES as readonly string[]).includes(value);
// Events that change what the transcript shows.
const CHANGES = new Set(["QUESTION_STARTED", "ANSWER_RECEIVED", "INTERVIEW_COMPLETED"]);

/** Follows an interview's live events (§91) while `enabled`, reconnecting from the last one
 * seen; returns whether it is connected. */
export function useLiveEvents(
  id: string,
  enabled: boolean,
  onEvent: (event: LiveEvent) => void,
): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    if (!enabled || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let stopped = false;
    let last: string | undefined;
    let retry: number | undefined;
    const open = () => {
      socket = new WebSocket(liveEventsUrl(id, last));
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        const event = JSON.parse(String(message.data)) as LiveEvent;
        if (event.type === "ping") return;
        last = event.id;
        handler.current(event);
      };
      socket.onclose = () => {
        setConnected(false);
        if (!stopped) retry = window.setTimeout(open, RECONNECT_MS);
      };
    };
    open();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [id, enabled]);
  return connected;
}

function clock(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
}

function SourceLine({ question }: { question: TranscriptQuestion }) {
  const t = useTranslations("interviews.session");
  const ref = question.source_ref as { quote?: string; page?: number | null; field?: string };
  if (question.source === "resume" && ref.quote) {
    return (
      <p className="text-muted-foreground text-xs">
        {ref.page
          ? t("sourceResumePage", { quote: ref.quote, page: ref.page })
          : t("sourceResume", { quote: ref.quote })}
      </p>
    );
  }
  return (
    <p className="text-muted-foreground text-xs">
      {isSource(question.source) ? t(`sources.${question.source}`) : question.source}
      {question.skill ? t("sourceSkill", { skill: question.skill }) : null}
      {question.difficulty ? t("sourceDifficulty", { difficulty: question.difficulty }) : null}
    </p>
  );
}

/** The interview's transcript (PRD §43): both sides in order, each question's source (§36),
 * the skills' coverage (§37) and the artifacts; while it runs, it follows the live events. */
export function TranscriptCard({ id, live }: { id: string; live: boolean }) {
  const t = useTranslations("interviews.session");
  const queryClient = useQueryClient();
  const transcript = useQuery({
    queryKey: sessionKeys.transcript(id),
    queryFn: () => getTranscript(id),
  });
  const connected = useLiveEvents(id, live, (event) => {
    if (CHANGES.has(event.type)) {
      void queryClient.invalidateQueries({ queryKey: sessionKeys.transcript(id) });
    }
  });

  if (transcript.isPending) return <Skeleton className="h-48 w-full lg:col-span-2" />;
  if (transcript.isError || !transcript.data) {
    return (
      <Card className="lg:col-span-2">
        <CardContent className="grid justify-items-start gap-2 pt-6">
          <p className="text-sm" role="alert">
            {t("loadFailed")}
          </p>
          <Button size="sm" variant="secondary" onClick={() => void transcript.refetch()}>
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }
  const data = transcript.data;
  const questions = new Map(data.questions.map((q) => [q.id, q]));
  const opened = new Set<string>();

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("coverage")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.coverage.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("notStarted")}</p>
          ) : (
            <ul className="grid gap-2 text-sm">
              {data.coverage.map((item) => (
                <li key={item.skill} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{item.skill}</span>
                  {item.required ? <Badge tone="info">{t("required")}</Badge> : null}
                  <Badge tone={item.covered ? "success" : "warning"}>
                    {item.covered ? t("covered") : t("notCovered")}
                  </Badge>
                  <span className="text-muted-foreground">
                    {t("asked", { asked: item.asked, planned: item.planned })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("artifacts")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.artifacts.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t(`transcriptStatus.${data.transcript_status}`)}
            </p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {data.artifacts.map((artifact) => (
                <li key={artifact.kind}>
                  <Button asChild size="sm" variant="secondary">
                    <a href={artifact.url}>{t(`artifactKinds.${artifact.kind}`)}</a>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t("transcript")}</CardTitle>
          {live ? (
            <Badge tone={connected ? "accent" : "neutral"}>
              {connected ? t("live") : t("connecting")}
            </Badge>
          ) : null}
        </CardHeader>
        <CardContent>
          {data.segments.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noSegments")}</p>
          ) : (
            <ol className="grid gap-3 text-sm">
              {data.segments.map((segment) => {
                const question = segment.question_id
                  ? questions.get(segment.question_id)
                  : undefined;
                const first =
                  segment.speaker === "ai" && question !== undefined && !opened.has(question.id);
                if (first && question) opened.add(question.id);
                return (
                  <li key={segment.seq} className="grid gap-0.5">
                    <p className="flex flex-wrap gap-x-2">
                      <span className="text-muted-foreground tabular-nums">
                        {clock(segment.start_ms)}
                      </span>
                      <span className="font-medium">{t(`speakers.${segment.speaker}`)}</span>
                      <span>{segment.text}</span>
                    </p>
                    {first && question ? <SourceLine question={question} /> : null}
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>
    </>
  );
}
