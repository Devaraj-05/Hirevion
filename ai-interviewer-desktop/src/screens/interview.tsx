import { Badge, Button, Label, Textarea } from "@hirevion/ui";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Room, RoomEvent } from "livekit-client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import {
  livekitTracks,
  nativeDeps,
  nativeOptions,
  openLocalTracks,
} from "../interview/native-services";
import { InterviewServices } from "../interview/services";
import {
  CONTROL_TOPIC,
  type ControlAction,
  controlMessage,
  formatClock,
  mergeState,
  parseStateMessage,
  STATE_TOPIC,
} from "../interview/session";
import { UPLOAD_POLL_MS, uploadView } from "../interview/upload";
import {
  commands,
  type InterviewState,
  type StartResult,
  type UploadProgress,
} from "../native/commands";
import { type ErrorKey, errorKey } from "./errors";
import { ErrorText } from "./shell";

const CAPTION_TOPIC = "lk.transcription";

/** PRD §32–33: the interview itself, fullscreen. Voice runs over LiveKit (the agent speaks and
 * listens; captions come from its transcription stream); text mode answers through the API. */
export function InterviewScreen({
  interviewId,
  start,
  onCompleted,
  onError,
}: {
  interviewId: string;
  start: StartResult;
  onCompleted: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("interview");
  const errors = useTranslations("errors");
  const id = useId();
  const [state, setState] = useState<InterviewState>(start.state);
  const [remaining, setRemaining] = useState(start.state.remaining_seconds);
  const [caption, setCaption] = useState("");
  const [answer, setAnswer] = useState("");
  const [connection, setConnection] = useState<"connecting" | "connected" | "reconnecting" | "off">(
    start.livekit_url ? "connecting" : "off",
  );
  const [error, setError] = useState<ErrorKey | null>(null);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [servicesProblem, setServicesProblem] = useState(false);
  const room = useRef<Room | null>(null);
  const services = useRef<InterviewServices | null>(null);
  const ended = useRef(false);

  const finish = useCallback(
    async (reason: "finished" | "candidate_ended") => {
      if (ended.current) return;
      ended.current = true;
      // Monitoring, the face module and the recording stop first, so their last events and
      // segments are saved while the interview is still open; the upload carries on after.
      await services.current?.stop();
      try {
        await commands.complete(interviewId, reason);
      } catch (failure) {
        onError(failure);
      }
      await room.current?.disconnect();
      onCompleted();
    },
    [interviewId, onCompleted, onError],
  );

  // Fullscreen for the whole interview (PRD §31); restored when it ends.
  useEffect(() => {
    const window = getCurrentWindow();
    void window.setFullscreen(true).catch(() => undefined);
    return () => void window.setFullscreen(false).catch(() => undefined);
  }, []);

  // The clock counts down locally between the agent's updates.
  useEffect(() => setRemaining(state.remaining_seconds), [state.remaining_seconds]);
  useEffect(() => {
    const timer = window.setInterval(
      () => setRemaining((seconds) => Math.max(0, seconds - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (state.status === "completed" || state.voice === "ended") void finish("finished");
  }, [state.status, state.voice, finish]);

  // The interview services (SP-08b): Rust's monitor, proctoring queue and recording, and the
  // webview's face module and camera/microphone recording that feed them.
  useEffect(() => {
    const created = new InterviewServices(interviewId, nativeDeps, {
      ...nativeOptions,
      onProblem: () => setServicesProblem(true),
      onReady: () => setServicesProblem(false),
    });
    services.current = created;
    // Text mode has no room to wait for: the services start now, on a camera and microphone
    // the app opens itself.
    if (!start.livekit_url || !start.participant_token) void created.start(openLocalTracks);
    return () => {
      created.dispose();
      if (services.current === created) services.current = null;
    };
  }, [interviewId, start.livekit_url, start.participant_token]);

  // Voice: join the room, publish the microphone and camera, listen to the agent.
  useEffect(() => {
    if (!start.livekit_url || !start.participant_token) return;
    const next = new Room({ adaptiveStream: true, dynacast: true });
    room.current = next;
    next.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== STATE_TOPIC) return;
      const patch = parseStateMessage(payload);
      if (patch) setState((current) => mergeState(current, patch));
    });
    next.on(RoomEvent.Reconnecting, () => setConnection("reconnecting"));
    next.on(RoomEvent.Reconnected, () => setConnection("connected"));
    next.registerTextStreamHandler(CAPTION_TOPIC, async (reader) => {
      setCaption(await reader.readAll());
    });
    next
      .connect(start.livekit_url, start.participant_token)
      .then(async () => {
        setConnection("connected");
        await next.localParticipant.setMicrophoneEnabled(true);
        await next.localParticipant.setCameraEnabled(true);
        // The same camera and microphone tracks go to the face module and the recorder.
        if (room.current === next) void services.current?.start(async () => livekitTracks(next));
      })
      .catch((failure: unknown) => {
        setConnection("off");
        setError(errorKey(failure));
        // The interview goes on in text mode, and so does the monitoring.
        if (room.current === next) void services.current?.start(openLocalTracks);
      });
    return () => {
      next.unregisterTextStreamHandler(CAPTION_TOPIC);
      void next.disconnect();
    };
  }, [start.livekit_url, start.participant_token]);

  function control(action: ControlAction) {
    void room.current?.localParticipant
      .publishData(controlMessage(action), { reliable: true, topic: CONTROL_TOPIC })
      .catch(() => undefined);
  }

  async function sendAnswer() {
    if (!state.question || !answer.trim()) return;
    try {
      const next = await commands.answer(interviewId, state.question.id, answer.trim());
      setAnswer("");
      setState(next.state);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    }
  }

  const textMode = state.answer_mode === "text";
  return (
    <section className="grid gap-5" aria-labelledby={`${id}-title`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id={`${id}-title`} className="font-semibold text-xl">
          {t("title")}
        </h1>
        <div className="flex items-center gap-2 text-sm">
          <Badge
            tone={
              connection === "connected" ? "success" : connection === "off" ? "neutral" : "warning"
            }
          >
            {t(`connection.${connection}`)}
          </Badge>
          <span className="font-mono text-lg">
            <span className="sr-only">{t("timeLeft")} </span>
            <time>{formatClock(remaining)}</time>
          </span>
        </div>
      </div>

      <div className="grid justify-items-center gap-3 py-6" aria-live="polite">
        <div
          className={`size-24 rounded-full ${state.voice === "speaking" ? "animate-pulse bg-accent" : "bg-surface-sunken"}`}
          aria-hidden
        />
        <p className="font-medium">{t(`voice.${state.voice}`)}</p>
        {caption ? (
          <p className="max-w-xl text-center text-muted-foreground text-sm">{caption}</p>
        ) : null}
      </div>

      {servicesProblem ? (
        <p role="status" className="rounded-md bg-warning-subtle p-3 text-sm text-warning">
          {t("servicesProblem")}
        </p>
      ) : null}

      {state.notice ? (
        <p role="alert" className="rounded-md bg-warning-subtle p-3 text-sm text-warning">
          {t("notice", { kind: state.notice.kind })}
        </p>
      ) : null}

      {state.question ? (
        <article className="grid gap-2 rounded-md border border-border p-4">
          <span className="text-muted-foreground text-xs">
            {t("questionNumber", { index: state.question.index })}
          </span>
          <p>{state.question.text}</p>
        </article>
      ) : null}

      {textMode || state.question ? (
        <div className="grid gap-2">
          <Label htmlFor={`${id}-answer`}>{textMode ? t("answerLabel") : t("typeInstead")}</Label>
          <Textarea
            id={`${id}-answer`}
            rows={5}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
          <Button
            className="w-fit"
            disabled={!answer.trim() || !state.question}
            onClick={() => void sendAnswer()}
          >
            {t("sendAnswer")}
          </Button>
        </div>
      ) : null}

      {error ? <ErrorText>{errors(error)}</ErrorText> : null}

      <div className="flex flex-wrap gap-2 border-border border-t pt-4">
        {connection === "connected" ? (
          <>
            <Button variant="secondary" onClick={() => control("done_answering")}>
              {t("controls.done")}
            </Button>
            <Button variant="secondary" onClick={() => control("repeat")}>
              {t("controls.repeat")}
            </Button>
            <Button variant="secondary" onClick={() => control("need_a_moment")}>
              {t("controls.moment")}
            </Button>
          </>
        ) : null}
        {confirmEnd ? (
          <>
            <Button variant="danger" onClick={() => void finish("candidate_ended")}>
              {t("endConfirm")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirmEnd(false)}>
              {t("keepGoing")}
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={() => setConfirmEnd(true)}>
            {t("end")}
          </Button>
        )}
      </div>
    </section>
  );
}

/** Asks Rust how much of the recording the server holds, until it holds all of it. */
function useUploadProgress(interviewId: string): UploadProgress | null {
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await commands.uploadProgress(interviewId);
        if (cancelled) return;
        setProgress(next);
        if (next.done) return;
      } catch {
        // Keep the last reading; "safe to close" needs an answer that says so.
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), UPLOAD_POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [interviewId]);
  return progress;
}

/** PRD §51: the app says it is safe to close only when every segment is acknowledged. */
export function CompletedScreen({
  interviewId,
  onBack,
}: {
  interviewId: string;
  onBack: () => void;
}) {
  const t = useTranslations("completed");
  const view = uploadView(useUploadProgress(interviewId));
  return (
    <section className="grid gap-4" aria-labelledby="completed-title">
      <h1 id="completed-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{t("body")}</p>
      <div className="grid gap-2" aria-live="polite">
        {view.state === "done" ? (
          <>
            <p role="status" className="font-medium text-success">
              {t("safeToClose")}
            </p>
            {view.gaps > 0 ? (
              <p className="text-muted-foreground text-sm">{t("gaps", { count: view.gaps })}</p>
            ) : null}
          </>
        ) : (
          <>
            <progress
              className="h-2 w-full accent-accent"
              max={100}
              value={view.state === "uploading" ? view.percent : undefined}
              aria-label={t("uploadLabel")}
            />
            <p className="text-muted-foreground text-sm">
              {view.state === "uploading"
                ? t("uploading", { percent: view.percent, pending: view.pending })
                : t("checking")}
            </p>
            <p className="font-medium">{t("keepOpen")}</p>
          </>
        )}
      </div>
      <Button variant="secondary" className="w-fit" onClick={onBack}>
        {t("back")}
      </Button>
    </section>
  );
}
