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
  /** The picture is taller than wide: the phone stands upright, so the candidate and the
   * laptop can't both fit (owner, 2026-11-15). It must be turned sideways. */
  portrait: boolean;
  green: boolean;
  personScore: number;
  laptopScore: number;
  /** The boxes the verdict used, for drawing on the preview. */
  personBox: Box | null;
  laptopBox: Box | null;
  /** Someone or something that shouldn't be there (owner, 2026-11-16): a second person, or a
   * laptop other than the candidate's. Never green while there is one. */
  extra: "person" | "laptop" | null;
  /** Their boxes, drawn in red. */
  others: Box[];
}

export const PERSON_MIN_SCORE = 0.5;
export const LAPTOP_MIN_SCORE = 0.4;
/** How close to an edge the laptop's box may come, as a share of the picture's side. */
export const EDGE_MARGIN = 0.01;
/** A second laptop counts from here: on the owner's picture the one across the desk scored
 * 0.41 and their own 0.33 (EfficientDet-Lite2, 2026-11-16). */
export const OTHER_LAPTOP_MIN_SCORE = 0.3;
/** A second person counts from this share of the picture (a face on a poster doesn't). */
export const OTHER_PERSON_MIN_AREA = 0.02;

function best(detections: Detection[], labels: Set<string>, min: number): Detection | null {
  let found: Detection | null = null;
  for (const detection of detections) {
    if (!labels.has(detection.label) || detection.score < min) continue;
    if (!found || detection.score > found.score) found = detection;
  }
  return found;
}

function centre(box: Box): { x: number; y: number } {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

function inside(point: { x: number; y: number }, box: Box): boolean {
  return (
    point.x >= box.x &&
    point.x <= box.x + box.width &&
    point.y >= box.y &&
    point.y <= box.y + box.height
  );
}

/** How much two boxes overlap: their intersection over their union. */
function overlap(a: Box, b: Box): number {
  const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  const overlap = width > 0 && height > 0 ? width * height : 0;
  const union = a.width * a.height + b.width * b.height - overlap;
  return union > 0 ? overlap / union : 0;
}

/** Two boxes for one laptop: the detector often sees one twice (lid and base). */
function sameLaptop(a: Box, b: Box): boolean {
  return overlap(a, b) >= 0.3 || inside(centre(a), b) || inside(centre(b), a);
}

/** Two boxes for one person. By overlap only: someone standing right behind a candidate who
 * fills the picture has their centre inside the candidate's box (review, 2026-11-16). */
function samePerson(a: Box, b: Box): boolean {
  return overlap(a, b) >= 0.5;
}

/** How far a box's centre is from the candidate (0 when it's in front of them). */
function distance(box: Box, person: Box | null): number {
  if (!person) return 0;
  const point = centre(box);
  const dx = Math.max(person.x - point.x, 0, point.x - (person.x + person.width));
  const dy = Math.max(person.y - point.y, 0, point.y - (person.y + person.height));
  return Math.hypot(dx, dy);
}

/** The candidate's own laptop: the one nearest them, the stronger guess on a tie. */
function nearest(
  detections: Detection[],
  label: string,
  person: Box | null,
  min: number,
): Detection | null {
  let found: Detection | null = null;
  for (const detection of detections) {
    if (detection.label !== label || detection.score < min) continue;
    if (
      !found ||
      distance(detection.box, person) < distance(found.box, person) ||
      (distance(detection.box, person) === distance(found.box, person) &&
        detection.score > found.score)
    ) {
      found = detection;
    }
  }
  return found;
}

/** Boxes of `label` other than `own`, each thing once. */
function othersOf(
  detections: Detection[],
  label: string,
  own: Box | null,
  keep: (detection: Detection) => boolean,
  same: (a: Box, b: Box) => boolean,
): Box[] {
  const found: Box[] = [];
  for (const detection of detections) {
    if (detection.label !== label || !keep(detection)) continue;
    if (own && same(detection.box, own)) continue;
    if (found.some((box) => same(box, detection.box))) continue;
    found.push(detection.box);
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
  // The laptop beside the candidate is theirs, even a faint one: it is never "another"
  // laptop (review, 2026-11-16). It counts as seen from LAPTOP_MIN_SCORE; failing that, its
  // keyboard does (a keyboard inside doesn't excuse a cut-off lid).
  const theirs = nearest(detections, "laptop", person?.box ?? null, OTHER_LAPTOP_MIN_SCORE);
  const laptop =
    theirs && theirs.score >= LAPTOP_MIN_SCORE
      ? theirs
      : nearest(detections, "keyboard", person?.box ?? null, LAPTOP_MIN_SCORE);
  const area = width * height;
  const people = othersOf(
    detections,
    "person",
    person?.box ?? null,
    (seen) =>
      seen.score >= PERSON_MIN_SCORE &&
      (seen.box.width * seen.box.height) / area >= OTHER_PERSON_MIN_AREA,
    samePerson,
  );
  const laptops = othersOf(
    detections,
    "laptop",
    theirs?.box ?? null,
    (seen) => seen.score >= OTHER_LAPTOP_MIN_SCORE,
    sameLaptop,
  );
  const extra = people.length > 0 ? "person" : laptops.length > 0 ? "laptop" : null;
  // Seen is enough: a candidate near the phone fills the picture, so their box reaches its
  // edges (owner's preview, 2026-11-16).
  const personPart: Part = person ? "ok" : "missing";
  let laptopPart: Part = "missing";
  if (laptop) {
    const edges = touches(laptop.box, width, height);
    // The whole laptop, keyboard included.
    laptopPart = edges.top || edges.bottom || edges.left || edges.right ? "cut" : "ok";
  }
  const portrait = height > width;
  return {
    person: personPart,
    laptop: laptopPart,
    portrait,
    green: !portrait && personPart === "ok" && laptopPart === "ok" && extra === null,
    personScore: person?.score ?? 0,
    laptopScore: laptop?.score ?? 0,
    personBox: person?.box ?? null,
    laptopBox: laptop?.box ?? null,
    extra,
    others: [...people, ...laptops],
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
