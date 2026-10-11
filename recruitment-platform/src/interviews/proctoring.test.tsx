import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderAdmin } from "@/test/render";
import { MonitoringPanel } from "./monitoring-panel";
import * as api from "./proctoring-api";
import {
  initialMonitor,
  isAfter,
  type MonitorState,
  monitorReducer,
  type StreamMessage,
} from "./proctoring-state";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./proctoring-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./proctoring-api")>()),
  getLiveSnapshot: vi.fn(),
  reviewEvent: vi.fn(),
}));

function event(over: Partial<api.ProctorEvent> = {}): api.ProctorEvent {
  return {
    id: "e-1",
    seq: 1,
    event: "PHONE_DETECTED",
    source: "camera",
    origin: "client",
    severity: "CRITICAL",
    started_at: "2026-10-12T05:00:10Z",
    duration_ms: 4000,
    ongoing: false,
    phase: null,
    confidence: 0.9,
    details: {},
    review_status: "pending",
    policy_version: 1,
    evidence_count: 0,
    review: null,
    ...over,
  };
}

function snapshot(over: Partial<api.LiveSnapshot> = {}): api.LiveSnapshot {
  return {
    interview: {
      status: "in_progress",
      started_at: "2026-10-12T05:00:00Z",
      deadline_at: "2026-10-12T05:45:00Z",
      duration_minutes: 45,
    },
    proctoring: {
      session: "open",
      devices: { camera: "up", mic: "up", screen: "down", third_eye: "unknown" },
      connection: { state: "ok", last_heartbeat_at: "2026-10-12T05:00:09Z" },
      displays: 1,
      cpu_percent: 30,
      vision_fps: 9.5,
      reported: {},
    },
    ai: { voice: "listening", agent_connected: true },
    counts: {
      total: 1,
      by_severity: { INFO: 0, WARNING: 0, CRITICAL: 1 },
      by_review: { pending: 1, confirmed: 0, false_positive: 0, not_relevant: 0 },
      dismissed: 0,
      open_alerts: 1,
    },
    events: [event()],
    transcript: [{ seq: 1, speaker: "ai", text: "Tell me about Redis.", start_ms: 0 }],
    cursor: "100-0",
    ...over,
  };
}

const message = (id: string, type: string, data: Record<string, unknown>): StreamMessage => ({
  id,
  type,
  data,
});

function loaded(): MonitorState {
  return monitorReducer(initialMonitor, { type: "snapshot", snapshot: snapshot() });
}

describe("monitorReducer", () => {
  it("starts from the snapshot", () => {
    const state = loaded();
    expect(state.ready).toBe(true);
    expect(state.events.map((e) => e.id)).toEqual(["e-1"]);
    expect(state.status?.devices.screen).toBe("down");
    expect(state.cursor).toBe("100-0");
    expect(state.transcript).toEqual([{ key: "s1", speaker: "ai", text: "Tell me about Redis." }]);
  });

  it("adds a new alert once, however often the stream repeats it", () => {
    const alert = event({ id: "e-2", severity: "WARNING", event: "WINDOW_MINIMIZED" });
    const once = monitorReducer(loaded(), {
      type: "stream",
      message: message("101-0", "PROCTOR_EVENT", { ...alert, change: "created" }),
    });
    const twice = monitorReducer(once, {
      type: "stream",
      message: message("101-0", "PROCTOR_EVENT", { ...alert, change: "created" }),
    });
    expect(twice).toBe(once);
    expect(once.events).toHaveLength(2);
    expect(once.counts.total).toBe(2);
    expect(once.counts.by_severity.WARNING).toBe(1);
    expect(once.cursor).toBe("101-0");
  });

  it("updates an episode in place and moves its counts when it gets worse", () => {
    const worse = event({ severity: "CRITICAL", event: "FACE_ABSENT", id: "e-3", duration_ms: 1 });
    let state = monitorReducer(loaded(), {
      type: "stream",
      message: message("101-0", "PROCTOR_EVENT", { ...worse, severity: "WARNING" }),
    });
    state = monitorReducer(state, {
      type: "stream",
      message: message("102-0", "PROCTOR_EVENT", { ...worse, duration_ms: 31_000 }),
    });
    expect(state.events.filter((e) => e.id === "e-3")).toHaveLength(1);
    expect(state.events.find((e) => e.id === "e-3")?.duration_ms).toBe(31_000);
    expect(state.counts.by_severity).toEqual({ INFO: 0, WARNING: 0, CRITICAL: 2 });
    expect(state.counts.total).toBe(2);
  });

  it("marks a dismissed event without removing it", () => {
    const state = monitorReducer(loaded(), {
      type: "stream",
      message: message("101-0", "PROCTOR_REVIEW", {
        event_id: "e-1",
        review_status: "false_positive",
        reviewer_id: "u-1",
        reason: "A poster",
      }),
    });
    const kept = state.events.find((e) => e.id === "e-1");
    expect(kept?.review_status).toBe("false_positive");
    expect(kept?.review?.reason).toBe("A poster");
    expect(state.counts.dismissed).toBe(1);
    expect(state.counts.open_alerts).toBe(0);
    expect(state.events).toHaveLength(1);
  });

  it("follows the devices, the AI and the transcript", () => {
    let state = loaded();
    state = monitorReducer(state, {
      type: "stream",
      message: message("101-0", "PROCTOR_STATUS", {
        ...snapshot().proctoring,
        devices: { camera: "down", mic: "up", screen: "up", third_eye: "unknown" },
      }),
    });
    state = monitorReducer(state, {
      type: "stream",
      message: message("102-0", "ANSWER_RECEIVED", { text: "It is a cache." }),
    });
    state = monitorReducer(state, {
      type: "stream",
      message: message("103-0", "AI_SPEAKING", { text: "And persistence?" }),
    });
    expect(state.status?.devices.camera).toBe("down");
    expect(state.ai.voice).toBe("speaking");
    expect(state.transcript.map((l) => l.text)).toEqual([
      "Tell me about Redis.",
      "It is a cache.",
      "And persistence?",
    ]);
  });

  it("ignores a message older than the cursor and keeps only the latest lines", () => {
    const state = monitorReducer(loaded(), {
      type: "stream",
      message: message("99-0", "PROCTOR_EVENT", event({ id: "old" })),
    });
    expect(state.events.map((e) => e.id)).toEqual(["e-1"]);
    let long = loaded();
    for (let n = 0; n < 12; n++) {
      long = monitorReducer(long, {
        type: "stream",
        message: message(`${200 + n}-0`, "ANSWER_RECEIVED", { text: `line ${n}` }),
      });
    }
    expect(long.transcript).toHaveLength(8);
    expect(long.transcript.at(-1)?.text).toBe("line 11");
  });

  it("compares stream ids by time, then sequence", () => {
    expect(isAfter("10-1", "10-0")).toBe(true);
    expect(isAfter("9-9", "10-0")).toBe(false);
    expect(isAfter("1-0", null)).toBe(true);
  });
});

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  close() {
    this.onclose?.();
  }
  send(body: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(body) });
  }
}

describe("MonitoringPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeSocket.all = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the devices and events, and a reconnect resumes from the last alert", async () => {
    vi.mocked(api.getLiveSnapshot).mockResolvedValue(snapshot());
    renderAdmin(<MonitoringPanel id="iv-1" live canReview={false} />);
    expect(await screen.findByText("Phone detected")).toBeInTheDocument();
    expect(screen.getByText("Camera")).toBeInTheDocument();
    await waitFor(() => expect(FakeSocket.all).toHaveLength(1));
    expect(FakeSocket.all[0]?.url).toContain("/api/v1/ws/proctoring/iv-1?after=100-0");

    act(() => {
      FakeSocket.all[0]?.onopen?.();
      FakeSocket.all[0]?.send({
        id: "101-0",
        type: "PROCTOR_EVENT",
        data: event({ id: "e-2", event: "MULTIPLE_FACES", severity: "CRITICAL" }),
      });
    });
    expect(await screen.findByText("More than one face")).toBeInTheDocument();

    // The socket drops; the panel starts again from the last alert it saw.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      act(() => FakeSocket.all[0]?.close());
      expect(await screen.findByText("Reconnecting")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(FakeSocket.all).toHaveLength(2));
    expect(FakeSocket.all[1]?.url).toContain("?after=101-0");
    act(() => {
      FakeSocket.all[1]?.send({
        id: "102-0",
        type: "PROCTOR_EVENT",
        data: event({ id: "e-3", event: "SCREEN_CAPTURE_STOPPED", severity: "CRITICAL" }),
      });
    });
    expect(await screen.findByText("Screen capture stopped")).toBeInTheDocument();
  });

  it("lets a recruiter dismiss an event with a reason, and keeps it listed", async () => {
    vi.mocked(api.getLiveSnapshot).mockResolvedValue(snapshot());
    vi.mocked(api.reviewEvent).mockResolvedValue(
      event({
        review_status: "false_positive",
        review: {
          outcome: "false_positive",
          reason: "A poster on the wall",
          reviewer_id: "u-1",
          reviewed_at: "2026-10-12T05:01:00Z",
        },
      }),
    );
    renderAdmin(<MonitoringPanel id="iv-1" live={false} canReview />);
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    await userEvent.click(screen.getByRole("button", { name: "False positive" }));
    const save = screen.getByRole("button", { name: "Save review" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason"), "A poster on the wall");
    await userEvent.click(save);
    await waitFor(() =>
      expect(api.reviewEvent).toHaveBeenCalledWith(
        "iv-1",
        "e-1",
        "false_positive",
        "A poster on the wall",
      ),
    );
    expect(await screen.findByText("Reviewed: A poster on the wall")).toBeInTheDocument();
    expect(screen.getByText("Phone detected")).toBeInTheDocument();
    expect(FakeSocket.all).toHaveLength(0); // the interview is over: no socket
  });

  it("offers no review to someone who can't decide", async () => {
    vi.mocked(api.getLiveSnapshot).mockResolvedValue(snapshot());
    renderAdmin(<MonitoringPanel id="iv-1" live canReview={false} />);
    await screen.findByText("Phone detected");
    expect(screen.queryByRole("button", { name: "Review" })).toBeNull();
  });
});
