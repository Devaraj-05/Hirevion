// Copies MediaPipe's WebAssembly module build into public/mediapipe/wasm so the app serves it
// itself (the desktop never loads code from a CDN). Only the ES-module variant is copied: the
// face worker is a module worker (`FilesetResolver.forVisionTasks(path, true)`), so the classic
// and no-SIMD variants (about 23 MB) would never load. Runs before `vite` dev and build.
import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const FILES = ["vision_wasm_module_internal.js", "vision_wasm_module_internal.wasm"];

const require = createRequire(import.meta.url);
const appRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const source = join(dirname(require.resolve("@mediapipe/tasks-vision")), "wasm");
const target = join(appRoot, "public", "mediapipe", "wasm");

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
for (const file of FILES) {
  const from = join(source, file);
  if (!existsSync(from)) {
    throw new Error(`MediaPipe file not found: ${from}`);
  }
  copyFileSync(from, join(target, file));
}
