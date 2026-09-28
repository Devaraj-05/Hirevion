import { useEffect, useState } from "react";
import { type ParsedRoute, parseRoute } from "./routes";

function useRoute(): ParsedRoute {
  const [parsed, setParsed] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onHashChange = () => setParsed(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return parsed;
}

export function App() {
  const { route } = useRoute();
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
      {route === "media" && <p>The media spike arrives with SP-00d Task 5.</p>}
      {route === "livekit" && <p>The LiveKit spike arrives with SP-00d Task 7.</p>}
    </main>
  );
}
