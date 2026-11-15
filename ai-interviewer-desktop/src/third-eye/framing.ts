/**
 * Whether the phone's picture shows the candidate and their whole laptop (C8-3, product owner,
 * 2026-11-15): only then does the phone step turn green and let the candidate continue.
 * Detections come from the on-device object detector (EfficientDet-Lite0, COCO labels).
 */

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Detection {
  label: string;
  score: number;
  /** In the picture's pixels. */
  box: Box;
}

/** `ok`: seen and inside the picture; `cut`: seen but running off an edge; `missing`: not seen. */
export type Part = "ok" | "cut" | "missing";

export interface Framing {
  person: Part;
  laptop: Part;
  green: boolean;
  personScore: number;
  laptopScore: number;
  /** The boxes the verdict used, for drawing on the preview. */
  personBox: Box | null;
  laptopBox: Box | null;
}

export const PERSON_MIN_SCORE = 0.5;
export const LAPTOP_MIN_SCORE = 0.4;
/** How close to an edge a box may come, as a share of the picture's side. */
export const EDGE_MARGIN = 0.02;

function best(detections: Detection[], labels: Set<string>, min: number): Detection | null {
  let found: Detection | null = null;
  for (const detection of detections) {
    if (!labels.has(detection.label) || detection.score < min) continue;
    if (!found || detection.score > found.score) found = detection;
  }
  return found;
}

interface Edges {
  top: boolean;
  bottom: boolean;
  left: boolean;
  right: boolean;
}

function touches(box: Box, width: number, height: number): Edges {
  const marginX = width * EDGE_MARGIN;
  const marginY = height * EDGE_MARGIN;
  return {
    top: box.y <= marginY,
    bottom: box.y + box.height >= height - marginY,
    left: box.x <= marginX,
    right: box.x + box.width >= width - marginX,
  };
}

export function framing(detections: Detection[], width: number, height: number): Framing {
  const person = best(detections, new Set(["person"]), PERSON_MIN_SCORE);
  // The whole laptop when the detector sees one (a keyboard inside doesn't excuse a cut-off
  // lid); its keyboard when that is all it recognises.
  const laptop =
    best(detections, new Set(["laptop"]), LAPTOP_MIN_SCORE) ??
    best(detections, new Set(["keyboard"]), LAPTOP_MIN_SCORE);
  let personPart: Part = "missing";
  if (person) {
    const edges = touches(person.box, width, height);
    // Their head and both sides must be in the picture; sitting at a desk, the legs needn't.
    personPart = edges.top || edges.left || edges.right ? "cut" : "ok";
  }
  let laptopPart: Part = "missing";
  if (laptop) {
    const edges = touches(laptop.box, width, height);
    // The whole laptop, keyboard included.
    laptopPart = edges.top || edges.bottom || edges.left || edges.right ? "cut" : "ok";
  }
  return {
    person: personPart,
    laptop: laptopPart,
    green: personPart === "ok" && laptopPart === "ok",
    personScore: person?.score ?? 0,
    laptopScore: laptop?.score ?? 0,
    personBox: person?.box ?? null,
    laptopBox: laptop?.box ?? null,
  };
}

interface Size {
  width: number;
  height: number;
}

/** Where `box` (in the picture's pixels) sits on a video element that letterboxes the picture
 * (`object-fit: contain`), for drawing it over the preview. */
export function toScreen(box: Box, picture: Size, element: Size): Box {
  const scale = Math.min(element.width / picture.width, element.height / picture.height);
  const offsetX = (element.width - picture.width * scale) / 2;
  const offsetY = (element.height - picture.height * scale) / 2;
  return {
    x: offsetX + box.x * scale,
    y: offsetY + box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
  };
}

/**
 * Holds the verdict steady: green only after `onForMs` of green pictures, so a lucky frame
 * isn't enough, and back to not green only after `offForMs` without one, so a missed frame
 * doesn't flicker.
 */
export class Steady {
  private green = false;
  private streakStart: number | null = null;
  private lastGreen = 0;

  constructor(
    private readonly onForMs: number,
    private readonly offForMs: number,
  ) {}

  update(seen: boolean, now: number): boolean {
    if (seen) {
      this.streakStart ??= now;
      this.lastGreen = now;
      if (!this.green && now - this.streakStart >= this.onForMs) this.green = true;
    } else if (this.green) {
      if (now - this.lastGreen >= this.offForMs) {
        this.green = false;
        this.streakStart = null;
      }
    } else {
      this.streakStart = null;
    }
    return this.green;
  }
}
