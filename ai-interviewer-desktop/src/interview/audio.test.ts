import { describe, expect, it } from "vitest";
import { type AudioRoom, PHONE_QUALITY, playInterviewerAudio } from "./audio";

/** A room that records its listeners and what was subscribed. */
function fakeRoom(existing: FakePublication[] = []) {
  const listeners = new Map<string, ((...args: never[]) => void)[]>();
  const room: AudioRoom & { emit: (event: string, ...args: unknown[]) => void } = {
    on(event, listener) {
      listeners.set(event, [...(listeners.get(event) ?? []), listener as never]);
      return room;
    },
    off(event, listener) {
      listeners.set(
        event,
        (listeners.get(event) ?? []).filter((known) => known !== (listener as never)),
      );
      return room;
    },
    remoteParticipants: new Map([
      ["agent", { identity: "agent", trackPublications: new Map(existing.entries()) }],
    ]),
    emit(event, ...args) {
      for (const listener of listeners.get(event) ?? []) listener(...(args as never[]));
    },
  };
  return room;
}

class FakePublication {
  subscribed: boolean | null = null;
  quality: number | null = null;
  constructor(
    readonly kind: "audio" | "video",
    readonly source = kind === "audio" ? "microphone" : "camera",
  ) {}
  setSubscribed(on: boolean) {
    this.subscribed = on;
  }
  setVideoQuality(quality: number) {
    this.quality = quality;
  }
}

class FakeTrack {
  readonly element = { remove: () => this.removed.push("element") } as unknown as HTMLMediaElement;
  removed: string[] = [];
  constructor(readonly kind: "audio" | "video") {}
  attach() {
    return this.element;
  }
  detach() {
    return [this.element];
  }
}

function sink() {
  const children: unknown[] = [];
  return { children, appendChild: (node: unknown) => children.push(node) };
}

describe("hearing the interviewer", () => {
  it("plays audio tracks: the silent interview of 2026-11-16 never attached them", () => {
    const room = fakeRoom();
    const into = sink();
    playInterviewerAudio(room, into);
    const voice = new FakeTrack("audio");
    room.emit("trackSubscribed", voice);
    expect(into.children).toEqual([voice.element]);
    room.emit("trackUnsubscribed", voice);
    expect(voice.removed).toEqual(["element"]);
  });

  it("subscribes to the interviewer's audio, and to no one else's video", () => {
    const early = [new FakePublication("audio"), new FakePublication("video")];
    const room = fakeRoom(early);
    playInterviewerAudio(room, sink());
    expect(early.map((publication) => publication.subscribed)).toEqual([true, null]);
    const late = [new FakePublication("video"), new FakePublication("audio")];
    for (const publication of late) room.emit("trackPublished", publication, { identity: "agent" });
    expect(late.map((publication) => publication.subscribed)).toEqual([null, true]);
  });

  it("shows the phone's camera at its low layer, so the laptop downloads little (C8-12)", () => {
    const camera = new FakePublication("video");
    const room = fakeRoom();
    const shown: unknown[] = [];
    playInterviewerAudio(room, sink(), (track) => shown.push(track));
    room.emit("trackPublished", camera, { identity: "third-eye-42" });
    expect(camera.subscribed).toBe(true);
    expect(camera.quality).toBe(PHONE_QUALITY);
    const video = new FakeTrack("video");
    room.emit("trackSubscribed", video, camera, { identity: "third-eye-42" });
    room.emit("trackUnsubscribed", video, camera, { identity: "third-eye-42" });
    expect(shown).toEqual([video, null]);
  });

  it("finds a phone already in the room when the join completes", () => {
    const camera = new FakePublication("video");
    const room = fakeRoom();
    playInterviewerAudio(room, sink(), () => undefined);
    room.remoteParticipants.set("third-eye-42", {
      identity: "third-eye-42",
      trackPublications: new Map([[0, camera]]),
    });
    room.emit("connected");
    expect(camera.subscribed).toBe(true);
  });

  it("subscribes to an interviewer already in the room once the join completes", () => {
    // Called before connect(): nobody is in the room yet, and joining fires no trackPublished
    // for tracks that were already there (review, 2026-11-16).
    const room = fakeRoom([]);
    playInterviewerAudio(room, sink());
    const voice = new FakePublication("audio");
    room.remoteParticipants.set("agent", {
      identity: "agent",
      trackPublications: new Map([[0, voice]]),
    });
    room.emit("connected");
    expect(voice.subscribed).toBe(true);
  });

  it("ignores video tracks and stops listening when released", () => {
    const room = fakeRoom();
    const into = sink();
    const release = playInterviewerAudio(room, into);
    room.emit("trackSubscribed", new FakeTrack("video"));
    release();
    room.emit("trackSubscribed", new FakeTrack("audio"));
    expect(into.children).toEqual([]);
  });
});
