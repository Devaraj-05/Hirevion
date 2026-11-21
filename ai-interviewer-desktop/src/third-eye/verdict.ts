import type { Framing } from "./framing";

/** What the phone's preview reports to the phone step (C8-3). */
export interface Verdict {
  /** Held green: the candidate and their whole laptop are in the picture. */
  green: boolean;
  /** The latest frame's verdict, or `null` before the first one. */
  framing: Framing | null;
  /** While green, the latest green frame's verdict: what the placement record carries. */
  evidence: Framing | null;
}

export const NOTHING: Verdict = { green: false, framing: null, evidence: null };

/** Whether the screen would show anything different; it re-renders only then. */
export function sameVerdict(a: Verdict, b: Verdict): boolean {
  return (
    a.green === b.green &&
    (a.framing === null) === (b.framing === null) &&
    a.framing?.portrait === b.framing?.portrait &&
    a.framing?.person === b.framing?.person &&
    a.framing?.laptop === b.framing?.laptop &&
    a.framing?.extra === b.framing?.extra &&
    a.evidence === b.evidence
  );
}

/** The status line under the phone's picture: what to fix first, as an i18n key. */
export function checkMessage(verdict: Verdict): string {
  const seen = verdict.framing;
  if (verdict.green) return "green";
  if (seen === null) return "checking";
  if (seen.portrait) return "portrait";
  if (seen.person === "missing") return "personMissing";
  if (seen.extra === "person") return "extraPerson";
  if (seen.extra === "laptop") return "extraLaptop";
  if (seen.laptop === "missing") return "laptopMissing";
  if (seen.laptop === "cut") return "laptopCut";
  return "hold";
}
