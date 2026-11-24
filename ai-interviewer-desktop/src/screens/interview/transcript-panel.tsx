import { ArrowDown, UserRound } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { activeLine, type Line } from "../../interview/transcript";
import { Emblem } from "../../ui/emblem";

/** How close to the bottom still counts as reading the latest line. */
const PINNED_PX = 32;

/**
 * Both voices, written as they're spoken (C8-12, owner's reference 2026-11-24): each turn is a
 * card with its speaker's mark and name, the AI Interviewer in blue and the candidate in violet;
 * words still being heard are lighter. It follows the conversation unless the candidate scrolls
 * back, then offers a way back to the latest line. Screen readers hear each line once, when its
 * words are final.
 */
export function TranscriptPanel({ lines }: { lines: Line[] }) {
  const t = useTranslations("interview.transcript");
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);

  // biome-ignore lint/correctness/useExhaustiveDependencies: follows each new or changed line.
  useLayoutEffect(() => {
    const element = scroller.current;
    if (following && element) element.scrollTop = element.scrollHeight;
  }, [lines, following]);

  const latest = () => {
    const element = scroller.current;
    if (!element) return;
    // At once: a smooth scroll's own scroll events would turn following off again.
    element.scrollTop = element.scrollHeight;
    setFollowing(true);
  };

  const lastFinal = lines.findLast((line) => line.final);
  const active = activeLine(lines);
  // LiveKit sends a turn as several segments: one card per run of the same speaker.
  const turns: Line[][] = [];
  for (const line of lines) {
    const run = turns.at(-1);
    if (run && run[0]?.speaker === line.speaker) run.push(line);
    else turns.push([line]);
  }
  const who = (line: Line) => (line.speaker === "interviewer" ? t("interviewer") : t("you"));

  return (
    <section className="transcript-pane" aria-labelledby="transcript-title">
      <h2 id="transcript-title" className="sr-only">
        {t("title")}
      </h2>
      <div
        ref={scroller}
        className="transcript-scroll"
        onScroll={(event) => {
          const element = event.currentTarget;
          setFollowing(element.scrollHeight - element.scrollTop - element.clientHeight < PINNED_PX);
        }}
      >
        {lines.length === 0 ? (
          <p className="transcript-empty">{t("empty")}</p>
        ) : (
          <ol className="transcript-lines">
            {turns.map((run) => {
              const first = run[0] as Line;
              return (
                <li
                  key={first.id}
                  className="turn"
                  data-speaker={first.speaker}
                  data-active={run.some((line) => line.id === active)}
                >
                  <span aria-hidden className="turn-avatar">
                    {first.speaker === "interviewer" ? (
                      <Emblem tone="light" className="size-5" />
                    ) : (
                      <UserRound className="size-5" strokeWidth={2} />
                    )}
                  </span>
                  <div className="turn-body">
                    <span className="turn-who">{who(first)}</span>
                    {run.map((line) => (
                      <p key={line.id} data-final={line.final}>
                        {line.text}
                      </p>
                    ))}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
      {following ? null : (
        <button type="button" className="jump-latest" onClick={latest}>
          <ArrowDown aria-hidden className="size-3.5" strokeWidth={2} />
          {t("latest")}
        </button>
      )}
      <p className="sr-only" aria-live="polite">
        {lastFinal ? `${who(lastFinal)}: ${lastFinal.text}` : ""}
      </p>
    </section>
  );
}
