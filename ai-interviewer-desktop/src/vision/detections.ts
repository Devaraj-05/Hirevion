import type { FaceBox } from "./types";

/** The parts of MediaPipe's `Detection` the module reads (pixel boxes, category scores). */
export interface DetectionLike {
  boundingBox?: { originX: number; originY: number; width: number; height: number };
  categories: ReadonlyArray<{ score: number }>;
}

const clamp = (value: number) => Math.min(1, Math.max(0, value));

/**
 * MediaPipe's detections as boxes normalised to the frame (0 to 1), clipped to it, best score
 * first. Detections without a box or a score are dropped.
 */
export function toFaceBoxes(
  detections: readonly DetectionLike[],
  frameWidth: number,
  frameHeight: number,
): FaceBox[] {
  if (frameWidth <= 0 || frameHeight <= 0) return [];
  const boxes: FaceBox[] = [];
  for (const detection of detections) {
    const box = detection.boundingBox;
    const score = detection.categories[0]?.score;
    if (!box || score === undefined) continue;
    const left = clamp(box.originX / frameWidth);
    const top = clamp(box.originY / frameHeight);
    const right = clamp((box.originX + box.width) / frameWidth);
    const bottom = clamp((box.originY + box.height) / frameHeight);
    boxes.push({ x: left, y: top, width: right - left, height: bottom - top, score });
  }
  return boxes.sort((a, b) => b.score - a.score);
}
