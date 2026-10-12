/** PRD §83's ten kinds of collection: the API's `CONSENT_PURPOSES`, in its order. The notices
 * page lists them, and a consent withdrawal names some of them. */
export const DISCLOSURES = [
  "camera",
  "microphone",
  "screen",
  "audio",
  "video",
  "third_eye",
  "transcript",
  "coding_activity",
  "system_telemetry",
  "proctoring_events",
] as const;

export type Disclosure = (typeof DISCLOSURES)[number];

export function isDisclosure(value: string): value is Disclosure {
  return DISCLOSURES.some((item) => item === value);
}
