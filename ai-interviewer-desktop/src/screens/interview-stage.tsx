import { cn } from "@hirevion/ui";
import { Lock, Mic, MonitorUp } from "lucide-react";
import { type ReactNode, useCallback, useId, useState } from "react";
import { useTranslations } from "use-intl";
import type { Health, Indicators } from "../interview/health";
import { type Connection, orbState } from "../interview/orb-state";
import type { Line } from "../interview/transcript";
import type { VoiceState } from "../native/commands";
import { Notice } from "../ui/kit";
import { CameraTile, type TileStatus, type VideoSource } from "./interview/camera-tile";
import { TopBar } from "./interview/top-bar";
import { TranscriptPanel } from "./interview/transcript-panel";
import { VoiceOrb } from "./interview/voice-orb";
import { WorkspaceColumn } from "./interview/workspace-column";

export type { Connection } from "../interview/orb-state";

const DOTS: Record<Health, string> = {
  starting: "bg-warning",
  ok: "bg-success",
  problem: "bg-danger",
};

const SESSION: Record<Connection, Health> = {
  connecting: "starting",
  connected: "ok",
  reconnecting: "starting",
  off: "ok",
};

/**
 * What the candidate sees during the interview (C8-12, product owner 2026-11-22): a bar with the
 * interview's name, the time left and End interview; then three columns. The left one is the
 * coding area, empty until a coding or design question opens. The centre is the interviewer, a
 * sphere that moves with the voice, and the live transcript of both speakers. The right one is the
 * main camera, the phone's camera, and the status of the microphone, the screen and the session.
 */
export function InterviewStage({
  title,
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

  const status = [
    { key: "microphone", icon: Mic, health: indicators.microphone },
    { key: "screen", icon: MonitorUp, health: indicators.screen },
    {
      key: "session",
      icon: Lock,
      health: voiceFailed ? ("problem" as const) : SESSION[connection],
    },
  ] as const;

  return (
    <div className="stage grid h-full grid-rows-[auto_minmax(0,1fr)]">
      <TopBar titleId={`${id}-title`} title={title} remaining={remaining} onEnd={onEnd} />

      <main
        aria-labelledby={`${id}-title`}
        className="stage-grid"
        data-workspace={open ? "open" : "closed"}
      >
        <WorkspaceColumn>{workspace}</WorkspaceColumn>

        <section className="centre-column" aria-label={t("interviewer")}>
          <div className="orb-stage">
            <VoiceOrb
              state={orb}
              interviewer={interviewerAudio}
              microphone={microphone}
              onVoiced={onVoiced}
            />
            <p className="orb-label" data-state={orb} aria-live="polite">
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
          <TranscriptPanel lines={lines} live={connection === "connected"} />
          {answerBox ? <div className="pane answer-pane">{answerBox}</div> : null}
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
          <ul className="status-row" aria-label={t("health.title")}>
            {status.map(({ key, icon: Icon, health }) => (
              <li
                key={key}
                className="status-item"
                title={`${t(`health.${key}`)}: ${t(`health.${health}`)}`}
              >
                <Icon aria-hidden className="size-4 text-muted-foreground" strokeWidth={1.75} />
                <span className="status-name">{t(`health.${key}`)}</span>
                <span className="status-state">
                  <span aria-hidden className={cn("size-1.5 rounded-full", DOTS[health])} />
                  {key !== "session"
                    ? t(`health.${health}`)
                    : voiceFailed
                      ? t("health.voiceUnavailable")
                      : t(`connection.${connection === "off" ? "connected" : connection}`)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
