import { Label, Textarea } from "@hirevion/ui";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { type RemoteTrack, Room, RoomEvent, Track } from "livekit-client";
import { CircleCheck } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { type AudioRoom, isPhoneCamera, playInterviewerAudio } from "../interview/audio";
import { reconcile } from "../interview/countdown";
import { indicators, type ServicePart } from "../interview/health";
import {
  livekitTracks,
  nativeDeps,
  nativeOptions,
  openLocalTracks,
} from "../interview/native-services";
import { InterviewServices, type LocalTracks } from "../interview/services";
import { mergeState, parseStateMessage, STATE_TOPIC } from "../interview/session";
import {
  isFinalSegment,
  type Line,
  SEGMENT_ID,
  speakerOf,
  TRANSCRIBED_TRACK,
  upsert,
} from "../interview/transcript";
import { typedAnswers, workspaceOf } from "../interview/workspace";
import { commands, type InterviewState, type StartResult } from "../native/commands";
import { type LiveThirdEye, liveView } from "../third-eye/pairing";
import { Notice, Panel, PillButton, ScreenTitle } from "../ui/kit";
import { CodingConsole } from "./coding-console";
import { type ErrorKey, errorKey } from "./errors";
import { mediaSource, type VideoSource } from "./interview/camera-tile";
import { EndDialog } from "./interview/end-dialog";
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
 * PRD §32–33: the interview itself, in the whole window. The candidate talks with the
 * interviewer and sees both voices written as they're spoken (C8-12, owner 2026-11-22), the
 * time left, End interview, and both cameras. A coding or design question opens its workspace in
 * the left column. Typed answers appear only where speech can't be used: an approved
 * text-answers accommodation, or no voice connection.
 */
export function InterviewScreen({
  interviewId,
  start,
  candidateName,
  jobTitle,
  onCompleted,
  onError,
}: {
  interviewId: string;
  start: StartResult;
  candidateName?: string | undefined;
  jobTitle?: string | undefined;
  onCompleted: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("interview");
  const errors = useTranslations("errors");
  const id = useId();
  const [state, setState] = useState<InterviewState>(start.state);
  const [remaining, setRemaining] = useState(start.state.remaining_seconds);
  const [lines, setLines] = useState<Line[]>([]);
  const [camera, setCamera] = useState<VideoSource | null>(null);
  const [phoneVideo, setPhoneVideo] = useState<VideoSource | null>(null);
  const [interviewerAudio, setInterviewerAudio] = useState<MediaStreamTrack | null>(null);
  const [microphone, setMicrophone] = useState<MediaStreamTrack | null>(null);
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

  // Closing the window mid-interview ends it for good (one attempt, C8-9): ask first, as End
  // Interview does. A crash or a killed app is a lost connection, which may rejoin once.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let live = true;
    void getCurrentWindow()
      .onCloseRequested((event) => {
        event.preventDefault();
        setConfirmEnd(true);
      })
      .then((stop) => {
        if (live) unlisten = stop;
        else stop();
      })
      .catch(() => undefined);
    return () => {
      live = false;
      unlisten?.();
    };
  }, []);

  // Fullscreen for the whole interview (PRD §31); restored when it ends.
  useEffect(() => {
    const window = getCurrentWindow();
    void window.setFullscreen(true).catch(() => undefined);
    return () => void window.setFullscreen(false).catch(() => undefined);
  }, []);

  // The clock counts down locally; the agent's time moves it only when they disagree (C8-12).
  // Every server message that carries the time resyncs it, even an unchanged value (a paused
  // clock repeats itself).
  const [clockSync, setClockSync] = useState(0);
  const adopt = useCallback((next: InterviewState) => {
    setState(next);
    setClockSync((count) => count + 1);
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: clockSync marks each server message.
  useEffect(
    () => setRemaining((local) => reconcile(local, state.remaining_seconds)),
    [state.remaining_seconds, clockSync],
  );
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
        adopt(now.state);
        return;
      }
      void finish("finished");
    }, TIME_UP_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [remaining, connection, interviewId, finish]);

  // Text mode opens the camera and microphone itself; the screen shows the same tracks.
  const openShown = useCallback(async (): Promise<LocalTracks> => {
    const tracks = await openLocalTracks();
    if (tracks.camera) setCamera(mediaSource(tracks.camera));
    setMicrophone(tracks.mic);
    return tracks;
  }, []);

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
    if (!start.livekit_url || !start.participant_token) void created.start(openShown);
    return () => {
      created.dispose();
      if (services.current === created) services.current = null;
    };
  }, [interviewId, start.livekit_url, start.participant_token, openShown]);

  // Voice: join the room, publish the microphone and camera, hear the interviewer, and see the
  // phone's camera at its low layer (C8-12).
  useEffect(() => {
    if (!start.livekit_url || !start.participant_token) return;
    // No adaptive stream: the only video taken is the phone's, at the layer asked for (with
    // adaptive stream on, LiveKit ignores a requested quality).
    const next = new Room({ adaptiveStream: false, dynacast: true });
    room.current = next;
    const stopAudio = speaker.current
      ? playInterviewerAudio(next as unknown as AudioRoom, speaker.current, (track) =>
          setPhoneVideo(track as unknown as VideoSource | null),
        )
      : () => undefined;
    // The interviewer's voice also drives the orb.
    const heard = (track: RemoteTrack, _: unknown, from: { identity: string }) => {
      if (track.kind === "audio" && !isPhoneCamera("video", from.identity)) {
        setInterviewerAudio(track.mediaStreamTrack);
      }
    };
    const gone = (track: RemoteTrack) => {
      if (track.kind === "audio") {
        setInterviewerAudio((now) => (now === track.mediaStreamTrack ? null : now));
      }
    };
    next.on(RoomEvent.TrackSubscribed, heard);
    next.on(RoomEvent.TrackUnsubscribed, gone);
    next.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== STATE_TOPIC) return;
      const patch = parseStateMessage(payload);
      if (!patch) return;
      setState((current) => mergeState(current, patch));
      if (patch.remaining_seconds !== undefined) setClockSync((count) => count + 1);
    });
    next.on(RoomEvent.Reconnecting, () => setConnection("reconnecting"));
    next.on(RoomEvent.Reconnected, () => setConnection("connected"));
    next.on(RoomEvent.AudioPlaybackStatusChanged, () => setSoundBlocked(!next.canPlaybackAudio));
    // Both voices, written as they're spoken: each utterance is a stream named by its segment.
    next.registerTextStreamHandler(CAPTION_TOPIC, async (reader, sender) => {
      const attributes = reader.info.attributes ?? {};
      const local = next.localParticipant;
      const speaker = speakerOf(
        sender.identity,
        local.identity,
        attributes[TRANSCRIBED_TRACK],
        [...local.trackPublications.values()].map((publication) => publication.trackSid),
      );
      const segment = attributes[SEGMENT_ID] ?? reader.info.id;
      const final = isFinalSegment(attributes);
      let spoken = "";
      for await (const chunk of reader) {
        spoken += chunk;
        const text = spoken;
        setLines((now) => upsert(now, { id: segment, speaker, text, final }));
      }
      // The final flag may come as the stream's trailer; the interviewer's words are complete
      // when its stream ends.
      const ended = isFinalSegment(reader.info.attributes) || speaker === "interviewer";
      if (ended && !final) {
        setLines((now) => upsert(now, { id: segment, speaker, text: spoken, final: true }));
      }
    });
    next
      // Audio only (`playInterviewerAudio`): the phone's video stays out of the laptop's download.
      .connect(start.livekit_url, start.participant_token, { autoSubscribe: false })
      .then(async () => {
        setConnection("connected");
        await next.localParticipant.setMicrophoneEnabled(true);
        await next.localParticipant.setCameraEnabled(true);
        if (room.current !== next) return;
        const own = next.localParticipant.getTrackPublication(Track.Source.Camera)?.track;
        setCamera(own ?? null);
        setMicrophone(livekitTracks(next).mic);
        // The same camera and microphone tracks go to the face module and the recorder.
        void services.current?.start(async () => livekitTracks(next));
      })
      .catch((failure: unknown) => {
        console.warn("interview: the voice room failed", failure);
        setConnection("off");
        setError(errorKey(failure));
        // The interview goes on with typed answers, and so does the monitoring.
        if (room.current === next) void services.current?.start(openShown);
      });
    return () => {
      stopAudio();
      next.off(RoomEvent.TrackSubscribed, heard);
      next.off(RoomEvent.TrackUnsubscribed, gone);
      next.unregisterTextStreamHandler(CAPTION_TOPIC);
      void next.disconnect();
    };
  }, [start.livekit_url, start.participant_token, openShown]);

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
      adopt((await commands.session(interviewId)).state);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    }
  }, [interviewId, onError]);

  // Text mode has no voice transcript: its questions and typed answers are written there instead.
  const typedMode = connection === "off";
  const asked = state.question;
  useEffect(() => {
    if (!typedMode || !asked?.text) return;
    setLines((now) =>
      upsert(now, { id: `q-${asked.id}`, speaker: "interviewer", text: asked.text, final: true }),
    );
  }, [typedMode, asked?.id, asked?.text]);

  async function sendAnswer() {
    if (!state.question || !answer.trim()) return;
    const question = state.question;
    const typedAnswer = answer.trim();
    try {
      const next = await commands.answer(interviewId, question.id, typedAnswer);
      setLines((now) =>
        upsert(now, {
          id: `a-${question.id}`,
          speaker: "candidate",
          text: typedAnswer,
          final: true,
        }),
      );
      setAnswer("");
      adopt(next.state);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    }
  }

  const question = state.question;
  // A coding question is answered in its console (ADR-0033), a design question has its notes pad.
  const workspace = workspaceOf(question);
  const typed = typedAnswers(state.answer_mode, connection, workspace);
  const title =
    candidateName && jobTitle ? t("barTitle", { name: candidateName, job: jobTitle }) : t("title");
  const phoneView = phone ? liveView(phone) : null;
  const phoneNote = !phone
    ? t("cameras.side.connecting")
    : phoneView?.alert
      ? t("cameras.side.lost")
      : phone === "connected"
        ? t("cameras.side.noPicture")
        : t("cameras.side.connecting");

  const work =
    question && workspace ? (
      <>
        <p className="workspace-question">{question.text}</p>
        {workspace === "code" ? (
          <CodingConsole
            key={question.id}
            interviewId={interviewId}
            questionId={question.id}
            onSubmitted={adopt}
            registerFlush={registerFlush}
            onClosed={() => void refresh()}
          />
        ) : (
          <NotesPad
            key={question.id}
            interviewId={interviewId}
            questionId={question.id}
            registerFlush={registerFlush}
          />
        )}
      </>
    ) : null;

  // The question itself is in the transcript; the box only takes the answer.
  const answerBox = typed ? (
    <div className="grid gap-2">
      {!question ? <p className="text-muted-foreground">{t("waitingForQuestion")}</p> : null}
      <Label htmlFor={`${id}-answer`}>{t("answerLabel")}</Label>
      <Textarea
        id={`${id}-answer`}
        rows={4}
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
  ) : null;

  return (
    <>
      <InterviewStage
        title={title}
        connection={connection}
        indicators={indicators(problems, phone)}
        remaining={remaining}
        voice={state.voice}
        lines={lines}
        workspace={work}
        answerBox={answerBox}
        camera={camera}
        phone={usesPhone ? phoneVideo : undefined}
        phoneNote={phoneNote}
        interviewerAudio={interviewerAudio}
        microphone={microphone}
        onEnd={() => setConfirmEnd(true)}
        voiceFailed={connection === "off" && state.answer_mode === "voice"}
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
            {phoneView?.alert ? <Notice role="alert">{t("phoneLost")}</Notice> : null}
            {problems && problems.size > 0 ? <Notice>{t("servicesProblem")}</Notice> : null}
            {notice && noticeShown ? (
              <Notice role="alert">{notice.text ?? t("noticeFallback")}</Notice>
            ) : null}
          </>
        }
      />

      {/* The interviewer's voice plays through here. */}
      <div ref={speaker} hidden />

      <EndDialog
        open={confirmEnd}
        onOpenChange={setConfirmEnd}
        onEnd={() => void finish("candidate_ended")}
      />
    </>
  );
}

/**
 * The end of the interview. Nothing to wait for (owner, 2026-11-21: "candidates should not wait
 * after closing the interview"): every answer and event is saved as it happens, the recording
 * uploads during the interview (PRD §50), and what is left uploads in the background or at the
 * next launch (§51).
 */
/** The interview is submitted (one attempt, C8-9): there is no way back into it, only out. */
export function CompletedScreen() {
  const t = useTranslations("completed");
  return (
    <section className="m-auto grid w-full max-w-xl gap-6" aria-labelledby="completed-title">
      <Panel className="grid justify-items-center gap-5 p-10 text-center">
        <CircleCheck className="size-12 text-success" strokeWidth={1.5} aria-hidden />
        <ScreenTitle
          id="completed-title"
          title={t("title")}
          lead={t("body")}
          className="justify-items-center"
        />
        <PillButton onClick={() => void getCurrentWindow().destroy()}>{t("close")}</PillButton>
      </Panel>
    </section>
  );
}
