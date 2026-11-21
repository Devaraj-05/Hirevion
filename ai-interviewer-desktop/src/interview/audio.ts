/**
 * Plays the interviewer's voice. LiveKit hands a subscribed audio track to the app, which must
 * attach it to an audio element: the interview of 2026-11-16 never did, so the AI spoke into a
 * room nobody heard. Only audio is subscribed to: the phone's video would otherwise be
 * downloaded back to the candidate's laptop for nothing.
 */

interface Publication {
  kind: string;
  setSubscribed(subscribed: boolean): void;
}

interface Track {
  kind: string;
  attach(): HTMLMediaElement;
  detach(): HTMLMediaElement[];
}

type Listener = (...args: never[]) => void;

/** What this needs of a LiveKit `Room` (joined with `autoSubscribe: false`). */
export interface AudioRoom {
  on(event: string, listener: Listener): unknown;
  off(event: string, listener: Listener): unknown;
  remoteParticipants: Map<string, { trackPublications: Map<unknown, Publication> }>;
}

interface Sink {
  appendChild(node: HTMLMediaElement): unknown;
}

/** Subscribes to every audio track and plays it into `sink`. Returns how to stop. */
export function playInterviewerAudio(room: AudioRoom, sink: Sink): () => void {
  const want = (publication: Publication) => {
    if (publication.kind === "audio") publication.setSubscribed(true);
  };
  const play = (track: Track) => {
    if (track.kind === "audio") sink.appendChild(track.attach());
  };
  const stop = (track: Track) => {
    if (track.kind !== "audio") return;
    for (const element of track.detach()) element.remove();
  };
  // Whoever was in the room first (the interviewer usually is): joining fires no
  // `trackPublished` for tracks already there, so they are looked up once the join completes.
  const present = () => {
    for (const participant of room.remoteParticipants.values()) {
      for (const publication of participant.trackPublications.values()) want(publication);
    }
  };
  room.on("trackPublished", want as Listener);
  room.on("trackSubscribed", play as Listener);
  room.on("trackUnsubscribed", stop as Listener);
  room.on("connected", present);
  present();
  return () => {
    room.off("connected", present);
    room.off("trackPublished", want as Listener);
    room.off("trackSubscribed", play as Listener);
    room.off("trackUnsubscribed", stop as Listener);
  };
}
