import { describe, expect, it } from "vitest";
import { kbps, summarizeConnection, videoSample } from "./stats";

type Entry = { id: string; type: string } & Record<string, unknown>;

function report(...entries: Entry[]): Map<string, Entry> {
  return new Map(entries.map((entry) => [entry.id, entry]));
}

const local: Entry = {
  id: "L1",
  type: "local-candidate",
  candidateType: "host",
  protocol: "udp",
};
const remote: Entry = {
  id: "R1",
  type: "remote-candidate",
  candidateType: "prflx",
  protocol: "udp",
};
const pair: Entry = {
  id: "CP1",
  type: "candidate-pair",
  localCandidateId: "L1",
  remoteCandidateId: "R1",
  state: "succeeded",
  nominated: true,
  currentRoundTripTime: 0.012,
};

describe("summarizeConnection", () => {
  it("follows the transport's selected candidate pair", () => {
    const other: Entry = { ...pair, id: "CP2", localCandidateId: "L2", currentRoundTripTime: 0.3 };
    const transport: Entry = { id: "T1", type: "transport", selectedCandidatePairId: "CP1" };
    expect(summarizeConnection(report(transport, other, pair, local, remote))).toEqual({
      protocol: "udp",
      localType: "host",
      remoteType: "prflx",
      rttMs: 12,
    });
  });

  it("falls back to the nominated, succeeded pair", () => {
    expect(summarizeConnection(report(pair, local, remote))?.rttMs).toBe(12);
  });

  it("reports TCP and relayed connections", () => {
    const tcpLocal: Entry = { ...local, candidateType: "relay", protocol: "tcp" };
    expect(summarizeConnection(report(pair, tcpLocal, remote))).toMatchObject({
      protocol: "tcp",
      localType: "relay",
    });
  });

  it("returns null until a pair is selected", () => {
    const checking: Entry = { ...pair, state: "in-progress", nominated: false };
    expect(summarizeConnection(report(checking, local, remote))).toBeNull();
    expect(summarizeConnection(report())).toBeNull();
  });
});

describe("videoSample", () => {
  it("reads the first inbound video stream", () => {
    const inbound: Entry = {
      id: "IV",
      type: "inbound-rtp",
      kind: "video",
      bytesReceived: 125_000,
      timestamp: 10_000,
      framesPerSecond: 15,
      frameWidth: 1280,
      frameHeight: 720,
      packetsLost: 3,
    };
    const audio: Entry = { id: "IA", type: "inbound-rtp", kind: "audio", bytesReceived: 9 };
    expect(videoSample(report(audio, inbound))).toEqual({
      direction: "inbound",
      bytes: 125_000,
      timestampMs: 10_000,
      fps: 15,
      width: 1280,
      height: 720,
      packetsLost: 3,
    });
  });

  it("reads outbound video when nothing is received", () => {
    const outbound: Entry = {
      id: "OV",
      type: "outbound-rtp",
      kind: "video",
      bytesSent: 50_000,
      timestamp: 2_000,
    };
    expect(videoSample(report(outbound))).toMatchObject({
      direction: "outbound",
      bytes: 50_000,
      fps: null,
      width: null,
    });
  });

  it("returns null without video", () => {
    expect(videoSample(report(local))).toBeNull();
  });
});

describe("kbps", () => {
  const sample = (bytes: number, timestampMs: number) => ({
    direction: "inbound" as const,
    bytes,
    timestampMs,
    fps: null,
    width: null,
    height: null,
    packetsLost: null,
  });

  it("is the bit rate between two samples", () => {
    expect(kbps(sample(0, 0), sample(125_000, 1_000))).toBe(1_000);
  });

  it("is null when time did not advance or the counter reset", () => {
    expect(kbps(sample(10, 1_000), sample(20, 1_000))).toBeNull();
    expect(kbps(sample(500, 1_000), sample(100, 2_000))).toBeNull();
  });
});
