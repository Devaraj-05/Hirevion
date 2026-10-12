import type { Counts, LiveSnapshot, ProctorEvent, ProctoringStatus } from "./proctoring-api";

/** What the live dashboard shows, and how the snapshot and the stream's events change it.
 * Pure: the component dispatches, this decides. Events are kept by id, so a replay after a
 * reconnect, or an event the snapshot already holds, changes nothing twice. */

export const MAX_EVENTS = 200;
export const TAIL = 8;

export interface TailLine {
  key: string;
  speaker: "ai" | "candidate";
  text: string;
}

export interface MonitorState {
  ready: boolean;
  interview: LiveSnapshot["interview"] | null;
  status: ProctoringStatus | null;
  ai: { voice: string | null; agentConnected: boolean };
  counts: Counts;
  events: ProctorEvent[];
  transcript: TailLine[];
  /** The id of the last stream message applied: where a reconnect resumes. */
  cursor: string | null;
  link: "connecting" | "live" | "reconnecting" | "unavailable";
}

export interface StreamMessage {
  id: string;
  type: string;
  at?: string;
  data: Record<string, unknown>;
}

export type MonitorAction =
  | { type: "snapshot"; snapshot: LiveSnapshot }
  | { type: "stream"; message: StreamMessage }
  | { type: "event"; event: ProctorEvent }
  | { type: "link"; link: MonitorState["link"] };

const NO_COUNTS: Counts = {
  total: 0,
  by_severity: { INFO: 0, WARNING: 0, CRITICAL: 0 },
  by_review: { pending: 0, confirmed: 0, false_positive: 0, not_relevant: 0 },
  dismissed: 0,
  open_alerts: 0,
};

export const initialMonitor: MonitorState = {
  ready: false,
  interview: null,
  status: null,
  ai: { voice: null, agentConnected: false },
  counts: NO_COUNTS,
  events: [],
  transcript: [],
  cursor: null,
  link: "connecting",
};

/** Whether stream id `a` ("ms-seq") is after `b`. */
export function isAfter(a: string, b: string | null): boolean {
  if (b === null) return true;
  const [aMs = 0, aSeq = 0] = a.split("-").map(Number);
  const [bMs = 0, bSeq = 0] = b.split("-").map(Number);
  return aMs !== bMs ? aMs > bMs : aSeq > bSeq;
}

const bump = (map: Record<string, number>, key: string, by: number) => ({
  ...map,
  [key]: Math.max(0, (map[key] ?? 0) + by),
});

/** The counts after `before` (if it was there) became `after`. */
function recount(counts: Counts, before: ProctorEvent | undefined, after: ProctorEvent): Counts {
  let next = counts;
  const apply = (event: ProctorEvent, by: number) => {
    const dismissed =
      event.review_status === "false_positive" || event.review_status === "not_relevant";
    next = {
      ...next,
      total: next.total + by,
      by_severity: bump(next.by_severity, event.severity, by),
      by_review: bump(next.by_review, event.review_status, by),
      dismissed: Math.max(0, next.dismissed + (dismissed ? by : 0)),
      open_alerts: Math.max(
        0,
        next.open_alerts +
          (event.severity !== "INFO" && event.review_status === "pending" ? by : 0),
      ),
    };
  };
  if (before) apply(before, -1);
  apply(after, 1);
  return next;
}

function byTime(a: ProctorEvent, b: ProctorEvent): number {
  return a.started_at < b.started_at ? 1 : a.started_at > b.started_at ? -1 : a.id < b.id ? 1 : -1;
}

function upsert(
  state: MonitorState,
  event: ProctorEvent,
  previousSeverity?: ProctorEvent["severity"] | null,
): MonitorState {
  // An event the list no longer holds (older than the snapshot or the cap) is still the same
  // event: the server says what severity it had, so the counts move instead of growing.
  const known = state.events.find((e) => e.id === event.id);
  const before = known ?? (previousSeverity ? { ...event, severity: previousSeverity } : undefined);
  const merged = { ...known, ...event, review: event.review ?? known?.review ?? null };
  const rest = state.events.filter((e) => e.id !== event.id);
  return {
    ...state,
    events: [merged, ...rest].sort(byTime).slice(0, MAX_EVENTS),
    counts: recount(state.counts, before, merged),
  };
}

function tail(state: MonitorState, line: TailLine): MonitorState {
  const last = state.transcript.at(-1);
  if (last && last.speaker === line.speaker && last.text === line.text) return state;
  return { ...state, transcript: [...state.transcript, line].slice(-TAIL) };
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stream(state: MonitorState, message: StreamMessage): MonitorState {
  if (!isAfter(message.id, state.cursor)) return state;
  const base = { ...state, cursor: message.id };
  const { data } = message;
  switch (message.type) {
    case "PROCTOR_EVENT":
      return upsert(
        base,
        data as unknown as ProctorEvent,
        data.previous_severity as ProctorEvent["severity"] | null | undefined,
      );
    case "PROCTOR_STATUS":
      return { ...base, status: data as unknown as ProctoringStatus };
    case "PROCTOR_REVIEW": {
      const target = base.events.find((e) => e.id === data.event_id);
      const outcome = data.review_status as ProctorEvent["review_status"];
      if (!target) {
        // Not listed any more: the server says what it was, so the counts still move.
        const stub = (status: unknown) =>
          ({ severity: data.severity, review_status: status }) as ProctorEvent;
        return { ...base, counts: recount(base.counts, stub(data.previous_status), stub(outcome)) };
      }
      return upsert(base, {
        ...target,
        review_status: outcome,
        review:
          outcome === "pending"
            ? null
            : {
                outcome,
                reason: text(data.reason),
                reviewer_id: text(data.reviewer_id),
                reviewed_at: message.at ?? new Date().toISOString(),
              },
      });
    }
    case "AI_SPEAKING":
      return tail(
        { ...base, ai: { ...base.ai, voice: "speaking" } },
        { key: message.id, speaker: "ai", text: text(data.text) },
      );
    case "CANDIDATE_SPEAKING":
      return { ...base, ai: { ...base.ai, voice: data.speaking ? "listening" : base.ai.voice } };
    case "ANSWER_RECEIVED":
      return tail(
        { ...base, ai: { ...base.ai, voice: "thinking" } },
        { key: message.id, speaker: "candidate", text: text(data.text) },
      );
    case "INTERVIEW_COMPLETED":
      return {
        ...base,
        ai: { ...base.ai, voice: "ended" },
        interview: base.interview ? { ...base.interview, status: "completed" } : null,
      };
    default:
      return base;
  }
}

function fromSnapshot(state: MonitorState, snapshot: LiveSnapshot): MonitorState {
  return {
    ...state,
    ready: true,
    interview: snapshot.interview,
    status: snapshot.proctoring,
    ai: { voice: snapshot.ai.voice, agentConnected: snapshot.ai.agent_connected },
    counts: snapshot.counts,
    events: [...snapshot.events].sort(byTime).slice(0, MAX_EVENTS),
    transcript: snapshot.transcript.slice(-TAIL).map((line) => ({
      key: `s${line.seq}`,
      speaker: line.speaker,
      text: line.text,
    })),
    cursor: isAfter(snapshot.cursor, state.cursor) ? snapshot.cursor : state.cursor,
  };
}

export function monitorReducer(state: MonitorState, action: MonitorAction): MonitorState {
  switch (action.type) {
    case "snapshot":
      return fromSnapshot(state, action.snapshot);
    case "stream":
      return stream(state, action.message);
    case "event":
      return upsert(state, action.event);
    case "link":
      return { ...state, link: action.link };
  }
}
