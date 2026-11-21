import { Dialog, DialogContent, Label, Textarea } from "@hirevion/ui";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Room, RoomEvent } from "livekit-client";
import { CircleCheck } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { type AudioRoom, playInterviewerAudio } from "../interview/audio";
import { captionWindow, isInterviewerCaption } from "../interview/captions";
import { indicators, type ServicePart } from "../interview/health";
import {
  livekitTracks,
  nativeDeps,
  nativeOptions,
  openLocalTracks,
} from "../interview/native-services";
import { InterviewServices } from "../interview/services";
import { mergeState, parseStateMessage, STATE_TOPIC } from "../interview/session";
import { UPLOAD_POLL_MS, uploadView } from "../interview/upload";
import {
  commands,
  type InterviewState,
  type StartResult,
  type UploadProgress,
} from "../native/commands";
import { type LiveThirdEye, liveView } from "../third-eye/pairing";
import { Notice, Panel, PillButton, ScreenTitle } from "../ui/kit";
import { CodingConsole } from "./coding-console";
import { type ErrorKey, errorKey } from "./errors";
import { type Connection, InterviewStage } from "./interview-stage";
import { NotesPad } from "./notes-pad";

const CAPTION_TOPIC = "lk.transcription";
/** How often the screen reads the third eye's status from Rust (its watcher reads every 5 s). */
const PHONE_POLL_MS = 5_000;
/** A reminder from the proctoring engine stays this long. */
const NOTICE_MS = 12_000;
/** How long after the clock reaches zero the app submits an interview the server hasn't. */
const TIME_UP_GRACE_MS = 30_000;

/**
 * PRD §32–33: the interview itself, in the whole window (product owner, 2026-11-16). The
 * interviewer is heard, and what it is saying shows as a caption while it speaks (at most 250
 * characters). There is nothing to press but Exit: the candidate just talks. A coding or
 * design question opens its workspace beside the interviewer. Typed answers appear only where
 * speech can't be used: an approved text-answers accommodation, or no voice connection.
 */
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
  const [connection, setConnection] = useState<Connection>(
    start.livekit_url ? "connecting" : "off",
  );
  const [error, setError] = useState<ErrorKey | null>(null);
  const [confirmEnd, setConfirmEnd] = useState(false);
  // Which parts of the monitoring and recording reported a problem; `null` until they first
  // all started.
  const [problems, setProblems] = useState<Set<ServicePart> | null>(null);
  const [soundBlocked, setSoundBlocked] = useState(false);
  const [phone, setPhone] = useState<LiveThirdEye | null>(null);
  const room = useRef<Room | null>(null);
  const speaker = useRef<HTMLDivElement>(null);
  const services = useRef<InterviewServices | null>(null);
  const ended = useRef(false);
  // The workspaces' unsaved text, saved before the interview ends (a save after `complete` is
  // refused).
  const flushers = useRef(new Set<() => Promise<void>>());
  const registerFlush = useCallback((flush: () => Promise<void>) => {
    flushers.current.add(flush);
    return () => {
      flushers.current.delete(flush);
    };
  }, []);

  const finish = useCallback(
    async (reason: "finished" | "candidate_ended") => {
      if (ended.current) return;
      ended.current = true;
      await Promise.all([...flushers.current].map((flush) => flush().catch(() => undefined)));
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

  // The interview lasts its set time, then is submitted (product owner, 2026-11-16). The
  // server closes it when its clock runs out; should that not arrive (no voice room, a lost
  // agent), the app submits it itself, after the interviewer's closing words.
  // Not while the room reconnects: the server may pause the clock and give the time back.
  useEffect(() => {
    if (remaining > 0 || connection === "connecting" || connection === "reconnecting") return;
    const timer = window.setTimeout(async () => {
      const now = await commands.session(interviewId).catch(() => null);
      if (now && now.state.status === "in_progress" && now.state.remaining_seconds > 0) {
        setState(now.state);
        return;
      }
      void finish("finished");
    }, TIME_UP_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [remaining, connection, interviewId, finish]);

  // The interview services (SP-08b): Rust's monitor, proctoring queue and recording, and the
  // webview's face module and camera/microphone recording that feed them.
  useEffect(() => {
    const created = new InterviewServices(interviewId, nativeDeps, {
      ...nativeOptions,
      onProblem: (part) => setProblems((now) => new Set(now ?? []).add(part)),
      onReady: () => setProblems(new Set()),
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

  // Voice: join the room, publish the microphone and camera, hear the interviewer.
  useEffect(() => {
    if (!start.livekit_url || !start.participant_token) return;
    const next = new Room({ adaptiveStream: true, dynacast: true });
    room.current = next;
    const stopAudio = speaker.current
      ? playInterviewerAudio(next as unknown as AudioRoom, speaker.current)
      : () => undefined;
    next.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== STATE_TOPIC) return;
      const patch = parseStateMessage(payload);
      if (patch) setState((current) => mergeState(current, patch));
    });
    next.on(RoomEvent.Reconnecting, () => setConnection("reconnecting"));
    next.on(RoomEvent.Reconnected, () => setConnection("connected"));
    next.on(RoomEvent.AudioPlaybackStatusChanged, () => setSoundBlocked(!next.canPlaybackAudio));
    // The newest utterance owns the caption: its words appear as they are spoken.
    let utterance = 0;
    next.registerTextStreamHandler(CAPTION_TOPIC, async (reader, speaking) => {
      if (!isInterviewerCaption(speaking.identity, next.localParticipant.identity)) return;
      utterance += 1;
      const mine = utterance;
      let spoken = "";
      for await (const chunk of reader) {
        if (mine !== utterance) return;
        spoken += chunk;
        setCaption(captionWindow(spoken));
      }
    });
    next
      // Audio only (`playInterviewerAudio`): the phone's video stays out of the laptop's download.
      .connect(start.livekit_url, start.participant_token, { autoSubscribe: false })
      .then(async () => {
        setConnection("connected");
        await next.localParticipant.setMicrophoneEnabled(true);
        await next.localParticipant.setCameraEnabled(true);
        // The same camera and microphone tracks go to the face module and the recorder.
        if (room.current === next) void services.current?.start(async () => livekitTracks(next));
      })
      .catch((failure: unknown) => {
        console.warn("interview: the voice room failed", failure);
        setConnection("off");
        setError(errorKey(failure));
        // The interview goes on with typed answers, and so does the monitoring.
        if (room.current === next) void services.current?.start(openLocalTracks);
      });
    return () => {
      stopAudio();
      next.unregisterTextStreamHandler(CAPTION_TOPIC);
      void next.disconnect();
    };
  }, [start.livekit_url, start.participant_token]);

  // The phone's camera, as Rust's watcher reports it to the server (every 5 s).
  const usesPhone = state.third_eye !== undefined && state.third_eye !== "off";
  useEffect(() => {
    if (!usesPhone) {
      setPhone(null);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const read = async () => {
      const value = await commands.thirdEyeLive().catch(() => null);
      if (cancelled) return;
      setPhone(value);
      timer = window.setTimeout(() => void read(), PHONE_POLL_MS);
    };
    void read();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [usesPhone]);

  // A reminder shows for a while, then leaves; the next one shows again.
  // Every state message repeats the open notice: it shows once per nudge (its id).
  const notice = state.notice;
  const noticeKey = notice ? (notice.id ?? notice.kind) : null;
  const [noticeShown, setNoticeShown] = useState(false);
  useEffect(() => {
    if (!noticeKey) return;
    setNoticeShown(true);
    const timer = window.setTimeout(() => setNoticeShown(false), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [noticeKey]);

  // A coding question closed elsewhere (answered, or its time ran out): fetch the state.
  const refresh = useCallback(async () => {
    try {
      setState((await commands.session(interviewId)).state);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    }
  }, [interviewId, onError]);

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

  const question = state.question;
  // A coding question is answered in its console (ADR-0033), a design question has its notes pad.
  const workspace =
    question?.workspace === "code" ? "code" : question?.workspace === "whiteboard" ? "notes" : null;
  // Typed answers only where speech can't be used.
  const typed = (state.answer_mode === "text" || connection === "off") && workspace !== "code";

  const side =
    workspace || typed ? (
      <>
        {question ? (
          <p className="text-[1.1rem] leading-relaxed">{question.text}</p>
        ) : (
          <p className="text-muted-foreground">{t("waitingForQuestion")}</p>
        )}
        {question && workspace === "code" ? (
          <CodingConsole
            key={question.id}
            interviewId={interviewId}
            questionId={question.id}
            onSubmitted={setState}
            registerFlush={registerFlush}
            onClosed={() => void refresh()}
          />
        ) : null}
        {question && workspace === "notes" ? (
          <NotesPad
            key={question.id}
            interviewId={interviewId}
            questionId={question.id}
            registerFlush={registerFlush}
          />
        ) : null}
        {typed ? (
          <div className="grid gap-2">
            <Label htmlFor={`${id}-answer`}>{t("answerLabel")}</Label>
            <Textarea
              id={`${id}-answer`}
              rows={6}
              className="rounded-xl"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
            />
            <PillButton
              className="w-fit"
              disabled={!answer.trim() || !question}
              onClick={() => void sendAnswer()}
            >
              {t("sendAnswer")}
            </PillButton>
          </div>
        ) : null}
      </>
    ) : null;

  return (
    <>
      <InterviewStage
        connection={connection}
        indicators={indicators(problems, phone)}
        remaining={remaining}
        voice={state.voice}
        caption={caption}
        side={side}
        onExit={() => setConfirmEnd(true)}
        notices={
          <>
            {soundBlocked ? (
              <div className="flex items-center gap-3 rounded-full bg-warning-subtle py-2 pr-2 pl-4 text-[0.9rem] text-warning">
                {t("soundBlocked")}
                <PillButton className="h-8 px-4" onClick={() => void room.current?.startAudio()}>
                  {t("turnOnSound")}
                </PillButton>
              </div>
            ) : null}
            {connection === "off" && state.answer_mode === "voice" ? (
              <Notice role="alert">
                {t("voiceUnavailable")}
                {error ? ` ${errors(error)}` : ""}
              </Notice>
            ) : null}
            {phone && liveView(phone).alert ? <Notice role="alert">{t("phoneLost")}</Notice> : null}
            {problems && problems.size > 0 ? <Notice>{t("servicesProblem")}</Notice> : null}
            {notice && noticeShown ? (
              <Notice role="alert">{notice.text ?? t("noticeFallback")}</Notice>
            ) : null}
          </>
        }
      />

      {/* The interviewer's voice plays through here. */}
      <div ref={speaker} hidden />

      <Dialog open={confirmEnd} onOpenChange={setConfirmEnd}>
        <DialogContent
          title={t("exitTitle")}
          description={t("exitBody")}
          closeLabel={t("keepGoing")}
          className="rounded-[20px]"
          footer={
            <>
              <PillButton variant="secondary" onClick={() => setConfirmEnd(false)}>
                {t("keepGoing")}
              </PillButton>
              <PillButton variant="danger" onClick={() => void finish("candidate_ended")}>
                {t("exitConfirm")}
              </PillButton>
            </>
          }
        />
      </Dialog>
    </>
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
  const done = view.state === "done";
  return (
    <section className="m-auto grid w-full max-w-xl gap-6" aria-labelledby="completed-title">
      <Panel className="grid justify-items-center gap-5 p-10 text-center">
        <CircleCheck className="size-12 text-success" strokeWidth={1.5} aria-hidden />
        <ScreenTitle
          id="completed-title"
          title={t("title")}
          lead={done ? t("bodyDone") : t("body")}
          className="justify-items-center"
        />
        <div className="grid w-full gap-2" aria-live="polite">
          {done ? (
            <>
              <p role="status" className="font-medium text-success">
                {t("safeToClose")}
              </p>
              {view.gaps > 0 ? (
                <p className="text-[0.9rem] text-muted-foreground">
                  {t("gaps", { count: view.gaps })}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <progress
                className="h-1.5 w-full overflow-hidden rounded-full accent-accent"
                max={100}
                value={view.state === "uploading" ? view.percent : undefined}
                aria-label={t("uploadLabel")}
              />
              <p className="text-[0.9rem] text-muted-foreground">
                {view.state === "uploading"
                  ? t("uploading", { percent: view.percent, pending: view.pending })
                  : t("checking")}
              </p>
              <p className="font-medium">{t("keepOpen")}</p>
            </>
          )}
        </div>
        <PillButton variant={done ? "primary" : "secondary"} onClick={onBack}>
          {t("back")}
        </PillButton>
      </Panel>
    </section>
  );
}
