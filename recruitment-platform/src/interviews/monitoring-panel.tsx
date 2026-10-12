"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  type BadgeTone,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Label,
  SeverityBadge,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useEffect, useId, useReducer, useRef, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  getLiveSnapshot,
  type ProctorEvent,
  type ProctoringStatus,
  proctoringSocketUrl,
  type ReviewOutcome,
  reviewEvent,
} from "./proctoring-api";
import {
  initialMonitor,
  type MonitorAction,
  type MonitorState,
  monitorReducer,
  type StreamMessage,
} from "./proctoring-state";

const RECONNECT_MS = 3000;
// Answers that asking again won't change.
const PERMANENT = new Set([401, 403, 404]);
const REVIEWS: ReviewOutcome[] = ["confirmed", "false_positive", "not_relevant"];

/** Loads an interview's monitoring snapshot and, while `live`, follows it: the snapshot first,
 * then the websocket from the snapshot's cursor. When the socket drops it starts again after a
 * moment, from the last event applied, so the alerts that happened meanwhile arrive on
 * reconnecting. */
export function useLiveMonitor(
  id: string,
  live: boolean,
): [MonitorState, (action: MonitorAction) => void] {
  const [state, dispatch] = useReducer(monitorReducer, initialMonitor);
  const cursor = useRef<string | null>(null);
  cursor.current = state.cursor;
  useEffect(() => {
    if (typeof WebSocket === "undefined") return;
    let stopped = false;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    const unavailable = () => dispatch({ type: "link", link: "unavailable" });
    const later = () => {
      dispatch({ type: "link", link: "reconnecting" });
      if (!stopped) retry = window.setTimeout(connect, RECONNECT_MS);
    };
    const connect = async () => {
      try {
        const snapshot = await getLiveSnapshot(id);
        if (stopped) return;
        dispatch({ type: "snapshot", snapshot });
        if (!live) return;
        const after = cursor.current ?? snapshot.cursor;
        socket = new WebSocket(proctoringSocketUrl(id, after));
        socket.onopen = () => dispatch({ type: "link", link: "live" });
        socket.onmessage = (message) => {
          const body = JSON.parse(String(message.data)) as StreamMessage;
          if (body.type === "ping") return;
          dispatch({ type: "stream", message: body });
        };
        socket.onclose = (closed) => {
          // 4401 and 4403 are the server saying no: asking again would only repeat it.
          if (closed.code === 4401 || closed.code === 4403) unavailable();
          else later();
        };
      } catch (error) {
        if (isApiProblem(error) && PERMANENT.has(error.status)) unavailable();
        else if (live) later();
        else unavailable();
      }
    };
    void connect();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [id, live]);
  return [state, dispatch];
}

const DEVICE_TONES: Record<string, BadgeTone> = {
  up: "success",
  down: "danger",
  unknown: "neutral",
};

function Device({ name, value }: { name: string; value: string | undefined }) {
  const t = useTranslations("interviews.proctoring");
  const state = value ?? "unknown";
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span>{name}</span>
      <Badge tone={DEVICE_TONES[state] ?? "neutral"}>{t(`device.${state}` as "device.up")}</Badge>
    </div>
  );
}

function Health({ state }: { state: MonitorState }) {
  const t = useTranslations("interviews.proctoring");
  const status: ProctoringStatus | null = state.status;
  if (!status) return <p className="text-muted-foreground text-sm">{t("noSession")}</p>;
  const connection = status.connection.state;
  return (
    <div className="grid gap-2">
      <Device name={t("camera")} value={status.devices.camera} />
      <Device name={t("microphone")} value={status.devices.mic} />
      <Device name={t("screen")} value={status.devices.screen} />
      <Device name={t("thirdEye")} value={status.devices.third_eye} />
      <div className="flex items-center justify-between gap-2 text-sm">
        <span>{t("ai")}</span>
        <Badge tone={state.ai.agentConnected ? "success" : "neutral"}>
          {state.ai.voice
            ? t.has(`voice.${state.ai.voice}` as "voice.idle")
              ? t(`voice.${state.ai.voice}` as "voice.idle")
              : state.ai.voice
            : t("voice.idle")}
        </Badge>
      </div>
      <div className="flex items-center justify-between gap-2 text-sm">
        <span>{t("connection")}</span>
        <Badge tone={connection === "ok" ? "success" : connection === "gap" ? "danger" : "warning"}>
          {t(`connectionState.${connection}`)}
        </Badge>
      </div>
      {status.vision_fps != null || status.cpu_percent != null ? (
        <p className="text-muted-foreground text-xs">
          {t("load", { cpu: status.cpu_percent ?? 0, fps: status.vision_fps ?? 0 })}
        </p>
      ) : null}
    </div>
  );
}

function Review({
  interviewId,
  event,
  onDone,
}: {
  interviewId: string;
  event: ProctorEvent;
  onDone: (event: ProctorEvent) => void;
}) {
  const t = useTranslations("interviews.proctoring");
  const problems = useAdminProblem();
  const id = useId();
  const [outcome, setOutcome] = useState<ReviewOutcome | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!outcome) return;
    setBusy(true);
    try {
      onDone(await reviewEvent(interviewId, event.id, outcome, reason.trim()));
      toast.success(t("reviewed"), {});
      setOutcome(null);
      setReason("");
    } catch (error) {
      problems.show(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {REVIEWS.map((choice) => (
          <Button
            key={choice}
            size="sm"
            variant={outcome === choice ? "primary" : "secondary"}
            aria-pressed={outcome === choice}
            onClick={() => setOutcome(choice)}
          >
            {t(`outcome.${choice}`)}
          </Button>
        ))}
      </div>
      {outcome ? (
        <div className="grid gap-1">
          <Label htmlFor={`${id}-reason`}>{t("reason")}</Label>
          <Textarea
            id={`${id}-reason`}
            value={reason}
            maxLength={1000}
            onChange={(e) => setReason(e.target.value)}
          />
          <div>
            <Button size="sm" disabled={busy || reason.trim() === ""} onClick={() => void save()}>
              {t("saveReview")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EventRow({
  event,
  interviewId,
  canReview,
  onReviewed,
}: {
  event: ProctorEvent;
  interviewId: string;
  canReview: boolean;
  onReviewed: (event: ProctorEvent) => void;
}) {
  const t = useTranslations("interviews.proctoring");
  const [open, setOpen] = useState(false);
  const dismissed =
    event.review_status === "false_positive" || event.review_status === "not_relevant";
  const seconds = event.duration_ms == null ? null : Math.round(event.duration_ms / 1000);
  return (
    <li className="grid gap-1 border-b pb-2 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <SeverityBadge severity={event.severity} label={t(`severity.${event.severity}`)} />
        <span className={dismissed ? "text-muted-foreground line-through" : "font-medium"}>
          {t.has(`events.${event.event}` as "events.FACE_ABSENT")
            ? t(`events.${event.event}` as "events.FACE_ABSENT")
            : event.event}
        </span>
        {seconds != null && seconds > 0 ? (
          <span className="text-muted-foreground">{t("seconds", { seconds })}</span>
        ) : null}
        {event.ongoing ? <Badge tone="warning">{t("ongoing")}</Badge> : null}
        {event.review_status !== "pending" ? (
          <Badge tone={dismissed ? "neutral" : "info"}>{t(`outcome.${event.review_status}`)}</Badge>
        ) : null}
        <time className="text-muted-foreground ml-auto text-xs" dateTime={event.started_at}>
          {new Date(event.started_at).toLocaleTimeString()}
        </time>
      </div>
      {event.review ? (
        <p className="text-muted-foreground text-xs">
          {t("reviewedWith", { reason: event.review.reason })}
        </p>
      ) : null}
      {canReview ? (
        <div>
          <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
            {t("review")}
          </Button>
          {open ? (
            <Review
              interviewId={interviewId}
              event={event}
              onDone={(done) => {
                onReviewed(done);
                setOpen(false);
              }}
            />
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** The recruiter's live view of an interview (PRD §65, §66): the devices, the AI and the
 * connection, the recent proctoring events (each can be confirmed or dismissed, with a reason,
 * and stays in the report) and the transcript's tail. Fed by the snapshot and the websocket. */
export function MonitoringPanel({
  id,
  live,
  canReview,
}: {
  id: string;
  live: boolean;
  canReview: boolean;
}) {
  const t = useTranslations("interviews.proctoring");
  const [state, dispatch] = useLiveMonitor(id, live);
  if (!state.ready) {
    if (state.link === "unavailable") {
      return (
        <Card className="lg:col-span-2">
          <CardContent className="pt-6">
            <p className="text-muted-foreground text-sm" role="status">
              {t("unavailable")}
            </p>
          </CardContent>
        </Card>
      );
    }
    return <Skeleton className="h-48 w-full lg:col-span-2" />;
  }
  const reviewed = (event: ProctorEvent) => dispatch({ type: "event", event });
  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("title")}</CardTitle>
        <Badge tone={state.link === "live" ? "accent" : "neutral"}>
          {live ? t(`link.${state.link}`) : t("link.ended")}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-3">
        <section className="grid content-start gap-3" aria-label={t("health")}>
          <h3 className="font-medium text-sm">{t("health")}</h3>
          <Health state={state} />
          <p className="text-muted-foreground text-xs">
            {t("counts", {
              critical: state.counts.by_severity.CRITICAL ?? 0,
              warning: state.counts.by_severity.WARNING ?? 0,
              dismissed: state.counts.dismissed,
            })}
          </p>
        </section>
        <section className="grid content-start gap-3 lg:col-span-2" aria-label={t("recent")}>
          <h3 className="font-medium text-sm">{t("recent")}</h3>
          {state.events.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noEvents")}</p>
          ) : (
            <ol className="grid gap-2">
              {state.events.slice(0, 20).map((event) => (
                <EventRow
                  key={event.id}
                  event={event}
                  interviewId={id}
                  canReview={canReview}
                  onReviewed={reviewed}
                />
              ))}
            </ol>
          )}
        </section>
        <section
          className="grid content-start gap-2 lg:col-span-3"
          aria-label={t("transcriptTail")}
        >
          <h3 className="font-medium text-sm">{t("transcriptTail")}</h3>
          {state.transcript.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noTranscript")}</p>
          ) : (
            <ol className="grid gap-1 text-sm">
              {state.transcript.map((line) => (
                <li key={line.key} className="flex gap-2">
                  <span className="font-medium">{t(`speaker.${line.speaker}`)}</span>
                  <span>{line.text}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
