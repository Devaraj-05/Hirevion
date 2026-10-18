"use client";

import { createContext, useContext } from "react";

/** Where the review workspace lets evidence take the player: a quote's time becomes a button
 * that moves every track there. Outside the workspace there is no jump and a time is text. */
export const EvidenceJumpContext = createContext<((ms: number) => void) | null>(null);

export function useEvidenceJump(): ((ms: number) => void) | null {
  return useContext(EvidenceJumpContext);
}
