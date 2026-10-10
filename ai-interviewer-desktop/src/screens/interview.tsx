import { Badge, Button, Label, Textarea } from "@hirevion/ui";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Room, RoomEvent } from "livekit-client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import {
  CONTROL_TOPIC,
  type ControlAction,
  controlMessage,
  formatClock,
  mergeState,
  parseStateMessage,
  STATE_TOPIC,
} from "../interview/session";
import { commands, type InterviewState, type StartResult } from "../native/commands";
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
  const room = useRef<Room | null>(null);
  const ended = useRef(false);

  const finish = useCallback(
    async (reason: "finished" | "candidate_ended") => {
      if (ended.current) return;
      ended.current = true;
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
      })
      .catch((failure: unknown) => {
        setConnection("off");
        setError(errorKey(failure));
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

export function CompletedScreen({ onBack }: { onBack: () => void }) {
  const t = useTranslations("completed");
  return (
    <section className="grid gap-4" aria-labelledby="completed-title">
      <h1 id="completed-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{t("body")}</p>
      <Button variant="secondary" className="w-fit" onClick={onBack}>
        {t("back")}
      </Button>
    </section>
  );
}
