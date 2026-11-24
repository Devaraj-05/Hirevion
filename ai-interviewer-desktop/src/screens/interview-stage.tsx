import { type ReactNode, useCallback, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import type { Health, Indicators } from "../interview/health";
import { type Connection, orbState } from "../interview/orb-state";
import type { Line } from "../interview/transcript";
import type { VoiceState } from "../native/commands";
import { Notice } from "../ui/kit";
import { CameraTile, type TileStatus, type VideoSource } from "./interview/camera-tile";
import { type StatusItem, TopBar } from "./interview/top-bar";
import { TranscriptPanel } from "./interview/transcript-panel";
import { VoiceOrb, VoiceStrip } from "./interview/voice-orb";
import { Waves, WorkspaceColumn } from "./interview/workspace-column";

export type { Connection } from "../interview/orb-state";

const SESSION: Record<Connection, Health> = {
  connecting: "starting",
  connected: "ok",
  reconnecting: "starting",
  off: "ok",
};

/**
 * What the candidate sees during the interview (C8-12; product owner 2026-11-22, reference image
 * 2026-11-24): a floating bar with the interview's name, the microphone, screen and session, the
 * time left and End Interview; then three cards. The left one is the coding question, waiting
 * until the AI asks one. The centre is the interviewer, a glowing sphere that moves with the
 * voice, its state, the live transcript of both speakers and a waveform. The right one holds the
 * main camera and the phone's camera.
 */
export function InterviewStage({
  title,
  candidateName,
  jobTitle,
  connection,
  indicators,
  remaining,
  voice,
  lines,
  workspace,
  answerBox,
  camera,
  phone,
  phoneNote,
  interviewerAudio,
  microphone,
  notices,
  onEnd,
  voiceFailed = false,
  candidateSpeaking: shownSpeaking,
}: {
  title: string;
  candidateName?: string | undefined;
  jobTitle?: string | undefined;
  connection: Connection;
  indicators: Indicators;
  remaining: number;
  voice: VoiceState;
  lines: Line[];
  /** The open question's workspace, or null for the empty coding area. */
  workspace: ReactNode | null;
  /** Typed answers, where speech can't be used. */
  answerBox: ReactNode | null;
  camera: VideoSource | null;
  /** The phone's camera; `undefined` when the interview doesn't use one. */
  phone: VideoSource | null | undefined;
  /** What the side tile says when it has no picture. */
  phoneNote: string;
  interviewerAudio: MediaStreamTrack | null;
  microphone: MediaStreamTrack | null;
  notices: ReactNode;
  onEnd: () => void;
  /** The voice room failed (not an approved text mode): the session row says so. */
  voiceFailed?: boolean;
  /** The gallery's way to show the candidate speaking without a microphone. */
  candidateSpeaking?: boolean;
}) {
  const t = useTranslations("interview");
  const id = useId();
  const [candidateSpeaking, setCandidateSpeaking] = useState(false);
  const onVoiced = useCallback((speaking: boolean) => setCandidateSpeaking(speaking), []);
  const orb = orbState(voice, connection, shownSpeaking ?? candidateSpeaking);
  const open = workspace !== null;
  const cameraStatus: TileStatus = indicators.camera;
  const phoneStatus: TileStatus = indicators.phone ?? "off";

  const centre = useRef<HTMLElement>(null);
  const sessionHealth: Health = voiceFailed ? "problem" : SESSION[connection];
  const status: StatusItem[] = [
    {
      key: "microphone",
      health: indicators.microphone,
      label: `${t("health.microphone")}: ${t(`health.${indicators.microphone}`)}`,
    },
    {
      key: "screen",
      health: indicators.screen,
      label: `${t("health.screen")}: ${t(`health.${indicators.screen}`)}`,
    },
    {
      key: "session",
      health: sessionHealth,
      label: `${t("health.session")}: ${
        voiceFailed
          ? t("health.voiceUnavailable")
          : t(`connection.${connection === "off" ? "connected" : connection}`)
      }`,
    },
  ];

  return (
    <div className="stage">
      <TopBar
        titleId={`${id}-title`}
        title={title}
        name={candidateName}
        job={jobTitle}
        status={status}
        remaining={remaining}
        onEnd={onEnd}
      />

      <main
        aria-labelledby={`${id}-title`}
        className="stage-grid"
        data-workspace={open ? "open" : "closed"}
      >
        <WorkspaceColumn>{workspace}</WorkspaceColumn>

        <section ref={centre} className="card centre-column" aria-label={t("interviewer")}>
          <div className="orb-stage">
            <VoiceOrb
              state={orb}
              interviewer={interviewerAudio}
              microphone={microphone}
              onVoiced={onVoiced}
              levelTarget={centre}
            />
            <p className="orb-label" data-state={orb} aria-live="polite">
              <span aria-hidden className="status-dot" />
              {t(`orb.${orb}`)}
            </p>
            {/* What needs the candidate's attention, said once, never over the transcript. */}
            <div className="notices">
              {connection === "reconnecting" ? (
                <Notice role="status">{t("reconnectingNotice")}</Notice>
              ) : null}
              {notices}
            </div>
          </div>
          <TranscriptPanel lines={lines} />
          {answerBox ? <div className="answer-pane">{answerBox}</div> : null}
          <VoiceStrip />
          <Waves />
        </section>

        <section className="camera-column" aria-label={t("cameras.title")}>
          <CameraTile
            kind="main"
            source={camera}
            status={cameraStatus}
            note={cameraStatus === "problem" ? t("cameras.main.problem") : t("cameras.main.empty")}
          />
          {phone !== undefined ? (
            <CameraTile kind="side" source={phone} status={phoneStatus} note={phoneNote} />
          ) : null}
        </section>
      </main>
    </div>
  );
}
