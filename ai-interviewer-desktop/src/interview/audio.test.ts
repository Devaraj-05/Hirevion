import { describe, expect, it } from "vitest";
import { type AudioRoom, playInterviewerAudio } from "./audio";

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
    remoteParticipants: new Map([["agent", { trackPublications: new Map(existing.entries()) }]]),
    emit(event, ...args) {
      for (const listener of listeners.get(event) ?? []) listener(...(args as never[]));
    },
  };
  return room;
}

class FakePublication {
  subscribed: boolean | null = null;
  constructor(readonly kind: "audio" | "video") {}
  setSubscribed(on: boolean) {
    this.subscribed = on;
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

  it("subscribes to audio only, so the phone's video isn't downloaded back to the laptop", () => {
    const early = [new FakePublication("audio"), new FakePublication("video")];
    const room = fakeRoom(early);
    playInterviewerAudio(room, sink());
    expect(early.map((publication) => publication.subscribed)).toEqual([true, null]);
    const late = [new FakePublication("video"), new FakePublication("audio")];
    for (const publication of late) room.emit("trackPublished", publication);
    expect(late.map((publication) => publication.subscribed)).toEqual([null, true]);
  });

  it("subscribes to an interviewer already in the room once the join completes", () => {
    // Called before connect(): nobody is in the room yet, and joining fires no trackPublished
    // for tracks that were already there (review, 2026-11-16).
    const room = fakeRoom([]);
    playInterviewerAudio(room, sink());
    const voice = new FakePublication("audio");
    room.remoteParticipants.set("agent", { trackPublications: new Map([[0, voice]]) });
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
