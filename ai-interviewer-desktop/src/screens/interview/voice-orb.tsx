import { memo, useEffect, useRef } from "react";
import { follow, level, voiced } from "../../interview/levels";
import type { OrbState } from "../../interview/orb-state";

/**
 * The interviewer's presence (C8-12): a pearl sphere that moves with the real sound, the
 * interviewer's voice while it speaks and the candidate's microphone while they answer. The
 * levels are read every frame from Web Audio analysers and written to the `--level` CSS
 * variable, outside React's render: nothing re-renders per frame. `onVoiced` reports when the
 * candidate starts and stops speaking.
 */
export const VoiceOrb = memo(function VoiceOrb({
  state,
  interviewer,
  microphone,
  onVoiced,
}: {
  state: OrbState;
  interviewer: MediaStreamTrack | null;
  microphone: MediaStreamTrack | null;
  onVoiced: (speaking: boolean) => void;
}) {
  const orb = useRef<HTMLDivElement>(null);
  const current = useRef(state);
  current.current = state;
  const report = useRef(onVoiced);
  report.current = onVoiced;

  useEffect(() => {
    const element = orb.current;
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
  }, [interviewer, microphone]);

  return (
    <div ref={orb} className="orb" data-state={state} aria-hidden>
      <span className="orb-ring" />
      <span className="orb-ring orb-ring-outer" />
      <span className="orb-core" />
    </div>
  );
});
