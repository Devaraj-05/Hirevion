import { memo, type RefObject, useEffect, useRef } from "react";
import { follow, level, voiced } from "../../interview/levels";
import type { OrbState } from "../../interview/orb-state";

/**
 * The interviewer's presence (C8-12, owner's reference 2026-11-24): a glowing sphere, blue into
 * violet, inside soft concentric rings, with the waveform mark at its centre. It moves with the
 * real sound, the interviewer's voice while it speaks and the candidate's microphone while they
 * answer. The levels are read every frame from Web Audio analysers and written to the `--level`
 * CSS variable on `levelTarget` (the centre card, so its waveform strip moves too), outside
 * React's render: nothing re-renders per frame. `onVoiced` reports when the candidate starts and
 * stops speaking.
 */
export const VoiceOrb = memo(function VoiceOrb({
  state,
  interviewer,
  microphone,
  onVoiced,
  levelTarget,
}: {
  state: OrbState;
  interviewer: MediaStreamTrack | null;
  microphone: MediaStreamTrack | null;
  onVoiced: (speaking: boolean) => void;
  levelTarget?: RefObject<HTMLElement | null>;
}) {
  const orb = useRef<HTMLDivElement>(null);
  const current = useRef(state);
  current.current = state;
  const report = useRef(onVoiced);
  report.current = onVoiced;

  useEffect(() => {
    const element = levelTarget?.current ?? orb.current;
    if (!element || (!interviewer && !microphone) || typeof AudioContext === "undefined") return;
    const context = new AudioContext();
    void context.resume().catch(() => undefined);
    const meter = (track: MediaStreamTrack | null) => {
      if (!track) return null;
      const source = context.createMediaStreamSource(new MediaStream([track]));
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0;
      source.connect(analyser);
      return { source, analyser, data: new Uint8Array(analyser.fftSize) };
    };
    const voice = meter(interviewer);
    const mic = meter(microphone);
    const read = (from: typeof voice) => {
      if (!from) return 0;
      from.analyser.getByteTimeDomainData(from.data);
      return level(from.data);
    };
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    let shown = 0;
    let heard = 0;
    let speaking = false;
    let last = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const elapsed = now - last;
      last = now;
      const fromMic = read(mic);
      heard = follow(heard, fromMic, elapsed, 60);
      const nowSpeaking = voiced(heard, speaking);
      if (nowSpeaking !== speaking) {
        speaking = nowSpeaking;
        report.current(speaking);
      }
      const target =
        current.current === "speaking"
          ? read(voice)
          : current.current === "candidate"
            ? fromMic
            : 0;
      shown = follow(shown, still.matches ? 0 : target, elapsed);
      element.style.setProperty("--level", shown.toFixed(3));
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      voice?.source.disconnect();
      mic?.source.disconnect();
      element.style.setProperty("--level", "0");
      if (speaking) report.current(false);
      void context.close().catch(() => undefined);
    };
  }, [interviewer, microphone, levelTarget]);

  return (
    <div ref={orb} className="orb" data-state={state} aria-hidden>
      <span className="orb-ring orb-ring-3" />
      <span className="orb-ring orb-ring-2" />
      <span className="orb-ring orb-ring-1" />
      <span className="orb-core">
        <svg viewBox="0 0 24 24" className="orb-glyph" aria-hidden focusable="false">
          {[
            [5, 7],
            [8.5, 11],
            [12, 15],
            [15.5, 11],
            [19, 7],
          ].map(([x, height]) => (
            <rect
              key={x}
              x={(x as number) - 1}
              y={12 - (height as number) / 2}
              width={2}
              height={height}
              rx={1}
            />
          ))}
        </svg>
      </span>
    </div>
  );
});

/** Bars along the bottom of the centre card that rise and fall with the same level. */
const STRIP = [
  0.18, 0.26, 0.34, 0.3, 0.46, 0.38, 0.56, 0.48, 0.7, 0.58, 0.82, 0.66, 1, 0.66, 0.82, 0.58, 0.7,
  0.48, 0.56, 0.38, 0.46, 0.3, 0.34, 0.26, 0.18,
];

export const VoiceStrip = memo(function VoiceStrip() {
  return (
    <div className="voice-strip" aria-hidden>
      {STRIP.map((height, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed decorative pattern.
        <span key={index} style={{ "--h": height } as React.CSSProperties} />
      ))}
    </div>
  );
});
