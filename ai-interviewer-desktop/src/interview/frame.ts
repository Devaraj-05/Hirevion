/** The largest evidence picture: the server keeps pictures small (at most 2 MiB). */
const MAX_WIDTH = 1280;
const MAX_HEIGHT = 720;

/** The size a `width`×`height` frame is scaled to: never up, never past 1280×720. */
export function fitFrame(width: number, height: number): { width: number; height: number } {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, MAX_WIDTH / width, MAX_HEIGHT / height);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** One frame of `camera` as a JPEG of at most 1280×720. The track is shared with the
 * recording and the face module, so it is only read here, never stopped. */
export async function grabJpeg(camera: MediaStreamTrack): Promise<Uint8Array> {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = new MediaStream([camera]);
  try {
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
  } finally {
    video.pause();
    video.srcObject = null;
  }
}
