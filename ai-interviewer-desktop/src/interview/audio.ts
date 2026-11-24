/**
 * What the laptop takes from the interview's room: the interviewer's voice, and (C8-12) the
 * phone's camera for the side camera tile. LiveKit hands a subscribed audio track to the app,
 * which must attach it to an audio element: the interview of 2026-11-16 never did, so the AI spoke
 * into a room nobody heard. The phone's camera is taken at its lowest layer (about 180p), so the
 * laptop downloads a few hundred kbps rather than the 1.2 Mbps the phone sends to the recorder.
 */

import { VideoQuality } from "livekit-client";

/** The phone's identity in the room (`third_eye_identity`, interview_session/media.py). */
export const PHONE_PREFIX = "third-eye-";
/** The simulcast layer the side camera tile asks for. */
export const PHONE_QUALITY = VideoQuality.LOW;

interface Publication {
  kind: string;
  source?: string;
  setSubscribed(subscribed: boolean): void;
  setVideoQuality?(quality: VideoQuality): void;
}

interface Track {
  kind: string;
  attach(): HTMLMediaElement;
  detach(): HTMLMediaElement[];
}

interface Participant {
  identity: string;
}

type Listener = (...args: never[]) => void;

/** What this needs of a LiveKit `Room` (joined with `autoSubscribe: false`). */
export interface AudioRoom {
  on(event: string, listener: Listener): unknown;
  off(event: string, listener: Listener): unknown;
  remoteParticipants: Map<
    string,
    { identity?: string; trackPublications: Map<unknown, Publication> }
  >;
}

interface Sink {
  appendChild(node: HTMLMediaElement): unknown;
}

/** Whether a track is the phone's camera. */
export function isPhoneCamera(kind: string, identity: string | undefined): boolean {
  return kind === "video" && (identity ?? "").startsWith(PHONE_PREFIX);
}

/**
 * Subscribes to every audio track and plays it into `sink`; with `onPhoneVideo`, also to the
 * phone's camera, handed over as it arrives (and null when it leaves). Returns how to stop.
 */
export function playInterviewerAudio(
  room: AudioRoom,
  sink: Sink,
  onPhoneVideo?: (track: Track | null) => void,
): () => void {
  const want = (publication: Publication, participant?: Participant) => {
    if (publication.kind === "audio") publication.setSubscribed(true);
    else if (onPhoneVideo && isPhoneCamera(publication.kind, participant?.identity)) {
      publication.setSubscribed(true);
      publication.setVideoQuality?.(PHONE_QUALITY);
    }
  };
  const play = (track: Track, publication?: Publication, participant?: Participant) => {
    if (track.kind === "audio") sink.appendChild(track.attach());
    else if (onPhoneVideo && isPhoneCamera(track.kind, participant?.identity)) {
      if (publication) publication.setVideoQuality?.(PHONE_QUALITY);
      onPhoneVideo(track);
    }
  };
  const stop = (track: Track, _publication?: Publication, participant?: Participant) => {
    if (track.kind === "audio") {
      for (const element of track.detach()) element.remove();
    } else if (onPhoneVideo && isPhoneCamera(track.kind, participant?.identity)) {
      onPhoneVideo(null);
    }
  };
  // Whoever was in the room first (the interviewer usually is): joining fires no
  // `trackPublished` for tracks already there, so they are looked up once the join completes.
  const present = () => {
    for (const [key, participant] of room.remoteParticipants) {
      const who = { identity: participant.identity ?? key };
      for (const publication of participant.trackPublications.values()) want(publication, who);
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
