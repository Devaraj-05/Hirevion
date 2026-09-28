/**
 * Plain summaries of WebRTC statistics (`RTCStatsReport`): how the connection is made
 * (UDP or TCP, direct or relayed, round-trip time) and what the video looks like.
 */

type Stat = Record<string, unknown>;

/** `RTCStatsReport`, or any map of stats objects (tests use a `Map`). */
export interface StatsReportLike {
  values(): Iterable<unknown>;
}

export interface ConnectionSummary {
  /** `udp` or `tcp` on this side. */
  protocol: string;
  /** ICE candidate types: `host`, `srflx`, `prflx` or `relay`. */
  localType: string;
  remoteType: string;
  rttMs: number | null;
}

export interface VideoSample {
  direction: "inbound" | "outbound";
  bytes: number;
  timestampMs: number;
  fps: number | null;
  width: number | null;
  height: number | null;
  packetsLost: number | null;
}

function stats(report: StatsReportLike): Stat[] {
  return [...report.values()].filter(
    (value): value is Stat => typeof value === "object" && value !== null,
  );
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The selected candidate pair, or `null` while ICE is still checking. */
export function summarizeConnection(report: StatsReportLike): ConnectionSummary | null {
  const all = stats(report);
  const byId = new Map(all.map((stat) => [text(stat.id), stat]));
  const transport = all.find(
    (stat) => stat.type === "transport" && text(stat.selectedCandidatePairId) !== null,
  );
  const pair =
    (transport ? byId.get(text(transport.selectedCandidatePairId)) : undefined) ??
    all.find(
      (stat) =>
        stat.type === "candidate-pair" &&
        (stat.selected === true || (stat.nominated === true && stat.state === "succeeded")),
    );
  if (!pair) {
    return null;
  }
  const local = byId.get(text(pair.localCandidateId));
  const remote = byId.get(text(pair.remoteCandidateId));
  if (!local || !remote) {
    return null;
  }
  const rtt = number(pair.currentRoundTripTime);
  return {
    protocol: text(local.protocol) ?? "unknown",
    localType: text(local.candidateType) ?? "unknown",
    remoteType: text(remote.candidateType) ?? "unknown",
    rttMs: rtt === null ? null : Math.round(rtt * 1_000),
  };
}

/** The first video stream, received if there is one, otherwise sent. */
export function videoSample(report: StatsReportLike): VideoSample | null {
  const all = stats(report);
  const inbound = all.find((stat) => stat.type === "inbound-rtp" && stat.kind === "video");
  const outbound = all.find((stat) => stat.type === "outbound-rtp" && stat.kind === "video");
  const stat = inbound ?? outbound;
  if (!stat) {
    return null;
  }
  const direction = stat === inbound ? "inbound" : "outbound";
  return {
    direction,
    bytes: number(direction === "inbound" ? stat.bytesReceived : stat.bytesSent) ?? 0,
    timestampMs: number(stat.timestamp) ?? 0,
    fps: number(stat.framesPerSecond),
    width: number(stat.frameWidth),
    height: number(stat.frameHeight),
    packetsLost: number(stat.packetsLost),
  };
}

/** Kilobits per second between two samples; `null` if time didn't advance or the counter reset. */
export function kbps(previous: VideoSample, current: VideoSample): number | null {
  const elapsedMs = current.timestampMs - previous.timestampMs;
  const bytes = current.bytes - previous.bytes;
  if (elapsedMs <= 0 || bytes < 0) {
    return null;
  }
  return Math.round((bytes * 8) / elapsedMs);
}
