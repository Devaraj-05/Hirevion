import { Label, NativeSelect, Textarea } from "@hirevion/ui";
import { useEffect, useState } from "react";
import type { Health } from "../interview/health";
import type { Connection } from "../interview/orb-state";
import type { Line } from "../interview/transcript";
import type { VoiceState } from "../native/commands";
import { mediaSource, type VideoSource } from "../screens/interview/camera-tile";
import { EndDialog } from "../screens/interview/end-dialog";
import { InterviewStage } from "../screens/interview-stage";
import { Notice, PillButton } from "../ui/kit";

/**
 * The interview screen's looks, one state per `#/gallery?state=…`, for checking them by eye and
 * in Playwright (debug builds only, see App): the live screen needs a LiveKit room. The people,
 * job and cameras here are synthetic.
 */
const TITLE = "Meera Iyer – Backend Engineer – Interview";

const CONVERSATION: Line[] = [
  {
    id: "1",
    speaker: "interviewer",
    final: true,
    text: "Hello Meera, thanks for joining. This interview is monitored and recorded. Shall we begin?",
  },
  { id: "2", speaker: "candidate", final: true, text: "Yes, I'm ready." },
  {
    id: "3",
    speaker: "interviewer",
    final: true,
    text: "Your resume mentions moving reporting queries to PostgreSQL read replicas. What problem were you solving, and how did you check the replicas kept up?",
  },
  {
    id: "4",
    speaker: "candidate",
    final: true,
    text: "The ledger's monthly reports were locking the primary. We moved them to two replicas and watched replication lag in Grafana, alerting past five seconds.",
  },
  {
    id: "5",
    speaker: "interviewer",
    final: true,
    text: "What would you do when a report needs data fresher than the lag allows?",
  },
];

const LONG: Line[] = [
  ...CONVERSATION,
  ...Array.from(
    { length: 8 },
    (_, n): Line => ({
      id: `x${n}`,
      speaker: n % 2 ? "candidate" : "interviewer",
      final: true,
      text:
        n % 2
          ? "I'd route that one query to the primary behind a feature flag, with a timeout, and keep the rest on the replicas."
          : "How would you keep a Redis cache consistent with the ledger when a payment is refunded?",
    }),
  ),
];

interface Look {
  voice: VoiceState;
  connection: Connection;
  remaining: number;
  lines: Line[];
  interim?: Line;
  workspace?: "code" | "notes";
  phone?: "live" | "missing" | "none";
  services?: Partial<Record<"camera" | "microphone" | "screen", Health>>;
  notice?: string;
  typed?: boolean;
  dialog?: boolean;
}

const LOOKS: Record<string, Look> = {
  start: { voice: "speaking", connection: "connected", remaining: 1800, lines: [] },
  speaking: { voice: "speaking", connection: "connected", remaining: 1712, lines: CONVERSATION },
  listening: { voice: "listening", connection: "connected", remaining: 1650, lines: CONVERSATION },
  candidate: {
    voice: "listening",
    connection: "connected",
    remaining: 1598,
    lines: CONVERSATION,
    interim: {
      id: "6",
      speaker: "candidate",
      final: false,
      text: "I'd read that one from the primary, behind a",
    },
  },
  thinking: { voice: "thinking", connection: "connected", remaining: 1540, lines: CONVERSATION },
  reconnecting: {
    voice: "speaking",
    connection: "reconnecting",
    remaining: 1490,
    lines: CONVERSATION,
    services: { screen: "starting" },
  },
  coding: {
    voice: "listening",
    connection: "connected",
    remaining: 1100,
    lines: CONVERSATION,
    workspace: "code",
  },
  notes: {
    voice: "listening",
    connection: "connected",
    remaining: 900,
    lines: CONVERSATION,
    workspace: "notes",
  },
  // The owner's screen of 2026-11-25: three checks down, which widened the bar past the window.
  "services-down": {
    voice: "speaking",
    connection: "connected",
    remaining: 1300,
    lines: CONVERSATION,
    phone: "missing",
    services: { camera: "problem", microphone: "problem", screen: "problem" },
    notice:
      "Some of the checks that protect your interview didn't start. Keep going; we'll keep trying.",
  },
  "phone-missing": {
    voice: "speaking",
    connection: "connected",
    remaining: 1300,
    lines: CONVERSATION,
    phone: "missing",
    notice: "Your phone's camera disconnected. Unlock the phone and keep its page open.",
  },
  "low-time": { voice: "speaking", connection: "connected", remaining: 95, lines: CONVERSATION },
  "five-minutes": { voice: "listening", connection: "connected", remaining: 284, lines: LONG },
  long: { voice: "speaking", connection: "connected", remaining: 1020, lines: LONG },
  text: {
    voice: "listening",
    connection: "off",
    remaining: 1400,
    lines: [
      {
        id: "q-1",
        speaker: "interviewer",
        final: true,
        text: "Tell me about a time a database migration went wrong. What did you change after?",
      },
    ],
    typed: true,
    phone: "none",
  },
  "end-dialog": {
    voice: "listening",
    connection: "connected",
    remaining: 1200,
    lines: CONVERSATION,
    dialog: true,
  },
};

/** A synthetic camera: a soft room and a figure, drawn into a canvas stream. */
function useFakeCamera(seed: number, on: boolean): VideoSource | null {
  const [source, setSource] = useState<VideoSource | null>(null);
  useEffect(() => {
    if (!on) return;
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const context = canvas.getContext("2d");
    if (!context) return;
    const draw = () => {
      const wall = context.createLinearGradient(0, 0, 0, 480);
      wall.addColorStop(0, seed ? "#c9cfd8" : "#d8d2c8");
      wall.addColorStop(1, seed ? "#9aa3b0" : "#a99f92");
      context.fillStyle = wall;
      context.fillRect(0, 0, 640, 480);
      context.fillStyle = seed ? "#3b4250" : "#4a3f39";
      if (seed) {
        // The phone's view: the desk, the laptop and the candidate from the side.
        context.fillRect(120, 330, 400, 18);
        context.fillStyle = "#23272f";
        context.fillRect(300, 230, 170, 100);
        context.fillStyle = "#3b4250";
        context.beginPath();
        context.arc(200, 210, 46, 0, Math.PI * 2);
        context.fill();
        context.fillRect(150, 255, 100, 80);
      } else {
        context.beginPath();
        context.arc(320, 210, 78, 0, Math.PI * 2);
        context.fill();
        context.beginPath();
        context.ellipse(320, 470, 190, 150, 0, Math.PI, 0);
        context.fill();
      }
    };
    draw();
    const timer = window.setInterval(draw, 500);
    const [track] = canvas.captureStream(4).getVideoTracks();
    if (track) setSource(mediaSource(track));
    return () => {
      window.clearInterval(timer);
      track?.stop();
    };
  }, [seed, on]);
  return source;
}

const STARTER = "def merge_intervals(rows):\n    # rows: list of [start, end]\n    pass\n";

function Workspace({ kind }: { kind: "code" | "notes" }) {
  if (kind === "notes") {
    return (
      <>
        <p className="workspace-question">
          Sketch how you would split the payments service into smaller services. Note the boundaries
          and what each one owns.
        </p>
        <div className="grid gap-2">
          <Label htmlFor="gallery-notes">Your design notes</Label>
          <Textarea
            id="gallery-notes"
            rows={14}
            className="rounded-xl"
            defaultValue={"Client -> API -> idempotency keys table -> payment provider"}
          />
        </div>
      </>
    );
  }
  return (
    <>
      <p className="workspace-question">
        {
          "Write merge_intervals(rows) that merges overlapping [start, end] pairs and returns them sorted.\nExample: [[1, 3], [2, 6], [8, 9]] gives [[1, 6], [8, 9]]."
        }
      </p>
      <div className="grid gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Your code</h2>
          <span className="text-[0.85rem] text-muted-foreground tabular-nums">14:32 left</span>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="gallery-language">Language</Label>
          <NativeSelect
            id="gallery-language"
            defaultValue="python"
            options={[
              { value: "python", label: "Python" },
              { value: "sql", label: "SQL" },
            ]}
          />
        </div>
        <Label htmlFor="gallery-code">Code</Label>
        <Textarea
          id="gallery-code"
          rows={12}
          className="rounded-xl font-mono text-[0.9rem]"
          defaultValue={STARTER}
        />
        <p className="text-[0.85rem] text-muted-foreground">
          Your code isn't run. It's reviewed after the interview.
        </p>
        <PillButton className="w-fit">Submit code</PillButton>
      </div>
    </>
  );
}

/** `?audio=1`: a synthetic voice (a tone that rises and falls like speech) drives the orb, to
 * measure the screen's cost while the interviewer speaks (perf, 2026-11-24). */
function useSyntheticVoice(on: boolean): MediaStreamTrack | null {
  const [track, setTrack] = useState<MediaStreamTrack | null>(null);
  useEffect(() => {
    if (!on) return;
    const context = new AudioContext();
    const tone = context.createOscillator();
    const swell = context.createOscillator();
    const depth = context.createGain();
    const gain = context.createGain();
    tone.frequency.value = 180;
    swell.frequency.value = 3;
    depth.gain.value = 0.4;
    gain.gain.value = 0.5;
    swell.connect(depth).connect(gain.gain);
    const out = context.createMediaStreamDestination();
    tone.connect(gain).connect(out);
    tone.start();
    swell.start();
    void context.resume().catch(() => undefined);
    setTrack(out.stream.getAudioTracks()[0] ?? null);
    return () => {
      setTrack(null);
      void context.close();
    };
  }, [on]);
  return track;
}

export function Gallery() {
  const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const name = params.get("state") ?? "speaking";
  const voice = useSyntheticVoice(params.get("audio") === "1");
  const look = LOOKS[name] ?? LOOKS.speaking;
  const camera = useFakeCamera(0, look?.connection !== "connecting");
  const side = useFakeCamera(1, look?.phone === undefined || look.phone === "live");
  const [dialog, setDialog] = useState(look?.dialog ?? false);
  if (!look) return null;
  const lines = look.interim ? [...look.lines, look.interim] : look.lines;
  const phoneHealth: Health = look.phone === "missing" ? "problem" : "ok";
  return (
    <div className="h-full bg-background text-foreground">
      <InterviewStage
        title={TITLE}
        candidateName="Meera Iyer"
        jobTitle="Backend Engineer"
        connection={look.connection}
        indicators={{
          camera: look.services?.camera ?? "ok",
          microphone: look.services?.microphone ?? "ok",
          screen: look.services?.screen ?? "ok",
          phone: look.phone === "none" ? null : phoneHealth,
        }}
        remaining={look.remaining}
        voice={look.voice}
        lines={lines}
        workspace={look.workspace ? <Workspace kind={look.workspace} /> : null}
        answerBox={
          look.typed ? (
            <div className="grid gap-2">
              <Label htmlFor="gallery-answer">Your answer</Label>
              <Textarea id="gallery-answer" rows={4} className="rounded-xl" />
              <PillButton className="w-fit">Send answer</PillButton>
            </div>
          ) : null
        }
        camera={camera}
        phone={look.phone === "none" ? undefined : look.phone === "missing" ? null : side}
        phoneNote="Your phone isn't connected. Keep its page open."
        interviewerAudio={voice}
        microphone={null}
        notices={look.notice ? <Notice role="alert">{look.notice}</Notice> : null}
        onEnd={() => setDialog(true)}
        candidateSpeaking={name === "candidate"}
      />
      <EndDialog open={dialog} onOpenChange={setDialog} onEnd={() => setDialog(false)} />
    </div>
  );
}
