/** The largest evidence picture: the server keeps pictures small (at most 2 MiB). */
const MAX_WIDTH = 1280;
const MAX_HEIGHT = 720;

/** The size a `width`×`height` frame is scaled to: never up, never past 1280×720. */
export function fitFrame(width: number, height: number): { width: number; height: number } {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, MAX_WIDTH / width, MAX_HEIGHT / height);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** How long a grab may take; Rust stops waiting after 10 s anyway. */
const GRAB_TIMEOUT_MS = 5_000;

/** `work`, or a rejection once `ms` have passed (a stalled camera never fires its events). */
export function withTimeout<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("the camera gave no frame in time")), ms);
  });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

/** One frame of `camera` as a JPEG of at most 1280×720. The track is shared with the
 * recording and the face module, so it is only read here, never stopped. A camera that gives
 * no frame within five seconds ends the grab, and the hidden video stops with it. */
export async function grabJpeg(camera: MediaStreamTrack): Promise<Uint8Array> {
  const video = document.createElement("video");
  try {
    return await withTimeout(drawJpeg(video, camera), GRAB_TIMEOUT_MS);
  } finally {
    video.pause();
    video.srcObject = null;
  }
}

async function drawJpeg(video: HTMLVideoElement, camera: MediaStreamTrack): Promise<Uint8Array> {
  video.muted = true;
  video.playsInline = true;
  video.srcObject = new MediaStream([camera]);
  await video.play();
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    await new Promise((resolve) => video.addEventListener("loadeddata", resolve, { once: true }));
  }
  const size = fitFrame(video.videoWidth, video.videoHeight);
  if (size.width === 0) throw new Error("the camera has no picture");
  const canvas = new OffscreenCanvas(size.width, size.height);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no 2D canvas");
  context.drawImage(video, 0, 0, size.width, size.height);
  const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.85 });
  return new Uint8Array(await blob.arrayBuffer());
}
