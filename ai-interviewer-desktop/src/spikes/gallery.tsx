import { Label, Textarea } from "@hirevion/ui";
import { captionWindow } from "../interview/captions";
import type { VoiceState } from "../native/commands";
import { type Connection, InterviewStage } from "../screens/interview-stage";
import { Notice } from "../ui/kit";

/**
 * The interview's looks, one state per `#/gallery?state=…`, for checking them by eye and in
 * Playwright (debug builds only, see App): the live screen needs a LiveKit room.
 */
const SPOKEN =
  "Thanks, that's a clear overview of your work on the payments service. Let's go deeper into " +
  "Python. When a request handler in your service starts timing out under load, how would you " +
  "find out whether the time goes to the database, to the network, or to Python itself? " +
  "Walk me through the tools you would reach for first, what each one would tell you, and how " +
  "you would confirm the cause before changing any code.";

const STATES: Record<
  string,
  { voice: VoiceState; connection: Connection; remaining: number; caption?: string }
> = {
  speaking: { voice: "speaking", connection: "connected", remaining: 1712, caption: SPOKEN },
  short: {
    voice: "speaking",
    connection: "connected",
    remaining: 1650,
    caption: "Could you briefly introduce yourself and the work you've done recently?",
  },
  listening: { voice: "listening", connection: "connected", remaining: 1598 },
  thinking: { voice: "thinking", connection: "reconnecting", remaining: 1540 },
  notice: { voice: "speaking", connection: "connected", remaining: 95, caption: SPOKEN },
  side: { voice: "speaking", connection: "connected", remaining: 1200, caption: SPOKEN },
};

export function Gallery() {
  const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const name = params.get("state") ?? "speaking";
  const look = STATES[name] ?? STATES.speaking;
  if (!look) return null;
  return (
    <div className="h-full bg-background text-foreground">
      <InterviewStage
        connection={look.connection}
        indicators={{
          camera: "ok",
          microphone: "ok",
          screen: name === "notice" ? "problem" : "ok",
          phone: name === "thinking" ? "starting" : "ok",
        }}
        remaining={look.remaining}
        voice={look.voice}
        caption={look.caption ? captionWindow(look.caption) : ""}
        onExit={() => undefined}
        side={
          name === "side" ? (
            <>
              <p className="text-[1.1rem] leading-relaxed">
                Sketch how you would split the payments service into smaller services. Note the
                boundaries and what each one owns.
              </p>
              <div className="grid gap-2">
                <Label htmlFor="gallery-notes">Your notes</Label>
                <Textarea id="gallery-notes" rows={10} className="rounded-xl" />
              </div>
            </>
          ) : null
        }
        notices={
          name === "notice" ? (
            <Notice role="alert">
              We can't see your face. Please stay in front of the camera.
            </Notice>
          ) : null
        }
      />
    </div>
  );
}
