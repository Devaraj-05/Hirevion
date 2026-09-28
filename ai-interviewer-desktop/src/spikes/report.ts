import { invoke } from "@tauri-apps/api/core";

/** Settings for an unattended spike run (debug builds only; see src-tauri/src/spike.rs). */
export interface SpikeConfig {
  /** The page to open for an unattended run (`HV_SPIKE=<page>:<seconds>`), e.g. `#/media?auto=60`. */
  runHash: string | null;
  /** A short-lived LiveKit token from `uv run hv lk-token`, passed in HV_SPIKE_TOKEN. */
  livekitToken: string | null;
  livekitUrl: string;
}

export function spikeConfig(): Promise<SpikeConfig> {
  return invoke<SpikeConfig>("spike_config");
}

/**
 * Sends a spike page's measurements to Rust, which adds the CPU use of the app's whole
 * process tree and writes them under ai-interviewer-desktop/spike-results/. Returns the
 * file path.
 */
export function reportSpike(page: string, results: Record<string, unknown>): Promise<string> {
  return invoke<string>("spike_report", { page, results });
}
