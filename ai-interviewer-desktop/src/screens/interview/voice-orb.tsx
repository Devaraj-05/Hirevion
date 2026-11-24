import { memo, type Ref, type RefObject, useEffect, useRef } from "react";
import { follow, level, type Scales, scales, voiced } from "../../interview/levels";
import type { OrbState } from "../../interview/orb-state";

/**
 * The interviewer's presence (C8-12, owner's reference 2026-11-24): a glowing sphere, blue into
 * violet, inside soft concentric rings, with the waveform mark at its centre. It moves with the
 * real sound, the interviewer's voice while it speaks and the candidate's microphone while they
 * answer. The levels are read every frame from Web Audio analysers and set straight on five
 * transforms (the sphere, its three rings and `strip`), only when they change, outside React's
 * render. Each of those has its own compositor layer, so a frame is a GPU scale, never a repaint
 * or a restyle of the card (perf, 2026-11-24). `onVoiced` reports when the candidate starts and
 * stops speaking.
 */
export const VoiceOrb = memo(function VoiceOrb({
  state,
  interviewer,
  microphone,
  onVoiced,
  strip,
}: {
  state: OrbState;
  interviewer: MediaStreamTrack | null;
  microphone: MediaStreamTrack | null;
  onVoiced: (speaking: boolean) => void;
  /** The waveform strip, which moves with the same level. */
  strip?: RefObject<HTMLElement | null>;
}) {
  const orb = useRef<HTMLDivElement>(null);
  const current = useRef(state);
  current.current = state;
  const report = useRef(onVoiced);
  report.current = onVoiced;

  useEffect(() => {
    const element = orb.current;
    const sphere = element?.querySelector<HTMLElement>(".orb-core");
    const [one, two, three] = [1, 2, 3].map((n) =>
      element?.querySelector<HTMLElement>(`.orb-ring-${n}`),
    );
    if (
      !element ||
      !sphere ||
      !one ||
      !two ||
      !three ||
      (!interviewer && !microphone) ||
      typeof AudioContext === "undefined"
    )
      return;
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
    const apply = (to: Scales) => {
      sphere.style.transform = `scale(${to.core})`;
      one.style.transform = `scale(${to.rings[0]})`;
      two.style.transform = `scale(${to.rings[1]})`;
      three.style.transform = `scale(${to.rings[2]})`;
      if (strip?.current) strip.current.style.transform = `scaleY(${to.strip})`;
    };
    let shown = 0;
    let written = "";
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
      // Only a visible change is written: an unchanged value still costs a style pass.
      const value = shown.toFixed(2);
      if (value !== written) {
        written = value;
        apply(scales(Number(value)));
      }
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      voice?.source.disconnect();
      mic?.source.disconnect();
      apply(scales(0));
      if (speaking) report.current(false);
      void context.close().catch(() => undefined);
    };
  }, [interviewer, microphone, strip]);

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

export const VoiceStrip = memo(function VoiceStrip({ ref }: { ref?: Ref<HTMLDivElement> }) {
  return (
    <div ref={ref} className="voice-strip" aria-hidden>
      {STRIP.map((height, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed decorative pattern.
        <span key={index} style={{ "--h": height } as React.CSSProperties} />
      ))}
    </div>
  );
});
