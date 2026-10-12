// Starts `tauri-driver` for the duration of a run and always stops it again, whichever way the run
// ends. Stopping takes the whole process tree: msedgedriver and the app are its children, and a
// leftover tauri-driver would keep its port (4444) and break the next run.
import { spawn, spawnSync } from "node:child_process";

/** Stops a process and everything it started. Safe to call twice. */
export function stopProcessTree(child) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    child.kill("SIGKILL");
  }
}

/**
 * Starts `command args…` and waits until `ready()` is true, then calls `run(child)` and returns
 * its result. The driver is stopped afterwards, and also when it can't start, never becomes ready,
 * dies early, or `run` throws.
 */
export async function withDriver(options, run) {
  const { command, args, env, ready, timeoutMs = 15_000, onSpawn, stdio } = options;
  const child = spawn(command, args, { env, stdio: stdio ?? ["ignore", "inherit", "inherit"] });
  onSpawn?.(child);
  // The first thing that goes wrong with the driver, as a rejection to race against.
  const failed = new Promise((_, reject) => {
    child.once("error", (error) =>
      reject(new Error(`couldn't start ${command} (${error.message}).`)),
    );
    child.once("exit", (code, signal) =>
      reject(new Error(`${command} exited with code ${code ?? signal} before the run ended.`)),
    );
  });
  failed.catch(() => undefined); // an unobserved rejection after a normal end is not an error
  try {
    const deadline = Date.now() + timeoutMs;
    const pause = () => new Promise((resolve) => setTimeout(resolve, 250));
    // Each wait is raced against `failed`, so a driver that can't start or dies is noticed
    // at once (and the loop yields to the event loop, which delivers those events).
    while (!(await Promise.race([Promise.resolve(ready()).catch(() => false), failed]))) {
      if (Date.now() > deadline) {
        throw new Error(`${command} didn't become ready within ${timeoutMs} ms.`);
      }
      await Promise.race([pause(), failed]);
    }
    return await Promise.race([run(child), failed]);
  } finally {
    stopProcessTree(child);
  }
}
