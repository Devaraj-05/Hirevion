import { useEffect, useState } from "react";
import { type ParsedRoute, parseRoute } from "./routes";
import { LiveKitSpike } from "./spikes/livekit/LiveKitSpike";
import { type FaceMode, MediaSpike } from "./spikes/media/MediaSpike";
import { spikeConfig } from "./spikes/report";

function useRoute(): ParsedRoute {
  const [parsed, setParsed] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onHashChange = () => setParsed(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return parsed;
}

/** Seconds for an unattended run (`?auto=60`), or null. */
function autoSeconds(params: URLSearchParams): number | null {
  const seconds = Number(params.get("auto"));
  return Number.isInteger(seconds) && seconds > 0 ? seconds : null;
}

function faceMode(params: URLSearchParams): FaceMode {
  const mode = params.get("faces");
  return mode === "off" || mode === "cpu" ? mode : "gpu";
}

export function App() {
  const { route, params } = useRoute();

  useEffect(() => {
    // HV_SPIKE opens a spike page for an unattended run. Only debug Rust builds register the
    // command; in release builds the call fails and is ignored.
    spikeConfig()
      .then((config) => {
        if (config.runHash && window.location.hash !== config.runHash) {
          window.location.hash = config.runHash;
        }
      })
      .catch(() => undefined);
  }, []);

  return (
    <main className="shell">
      <header>
        <h1>Hirevion AI Interview</h1>
        <nav aria-label="Spikes">
          <a href="#/">Home</a>
          <a href="#/media">Media spike</a>
          <a href="#/livekit">LiveKit spike</a>
        </nav>
      </header>
      {route === "home" && <p>Desktop spike build (SP-00d). Choose a spike above.</p>}
      {route === "media" && (
        <MediaSpike autoSeconds={autoSeconds(params)} faceMode={faceMode(params)} />
      )}
      {route === "livekit" && <LiveKitSpike autoSeconds={autoSeconds(params)} />}
    </main>
  );
}
