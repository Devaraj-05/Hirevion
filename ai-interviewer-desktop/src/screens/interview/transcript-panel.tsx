import { ArrowDown } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { activeLine, type Line } from "../../interview/transcript";

/** How close to the bottom still counts as reading the latest line. */
const PINNED_PX = 32;

/**
 * Both voices, written as they're spoken (C8-12): the interviewer on the left, the candidate
 * ("You") on the right, words still being heard in a lighter tone. It follows the conversation
 * unless the candidate scrolls back, then offers a way back to the latest line. Screen readers
 * hear each line once, when its words are final.
 */
export function TranscriptPanel({ lines, live }: { lines: Line[]; live: boolean }) {
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
  const who = (line: Line) => (line.speaker === "interviewer" ? t("interviewer") : t("you"));

  return (
    <section className="pane transcript-pane" aria-labelledby="transcript-title">
      <header className="pane-header">
        <h2 id="transcript-title" className="pane-title">
          {t("title")}
        </h2>
        {live ? (
          <span className="live-label">
            <span aria-hidden className="live-dot" />
            {t("live")}
          </span>
        ) : null}
      </header>
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
            {lines.map((line, index) => {
              const first = lines[index - 1]?.speaker !== line.speaker;
              return (
                <li
                  key={line.id}
                  className="transcript-line"
                  data-speaker={line.speaker}
                  data-final={line.final}
                  data-first={first}
                  data-active={line.id === active}
                >
                  {first ? <span className="transcript-who">{who(line)}</span> : null}
                  <p>{line.text}</p>
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
