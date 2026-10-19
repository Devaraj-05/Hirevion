"use client";

import { newIdempotencyKey } from "@hirevion/api-client";
import { useRef } from "react";

/** An `Idempotency-Key` for a form: one per attempt, kept while the form is open so a retry of
 * the same submit is the same request, and made on first use (not on every render). */
export function useIdempotencyKey() {
  const key = useRef<string | null>(null);
  return {
    /** The key for this attempt. */
    current(): string {
      key.current ??= newIdempotencyKey();
      return key.current;
    },
    /** After a success: the next submit is a new request. */
    renew(): void {
      key.current = null;
    },
  };
}
