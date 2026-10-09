import { Toaster } from "@hirevion/ui";
import { lazy, Suspense, useCallback, useEffect, useReducer, useState } from "react";
import { type FlowEvent, initialState, transition } from "./flow/flow";
import { I18nProvider, type Locale, pickLocale } from "./i18n/i18n";
import { commands, type ReleaseState, type SignInResult } from "./native/commands";
import { isSessionLost } from "./screens/errors";
import { InterviewsScreen } from "./screens/interviews";
import { LaunchScreen, ReadyScreen, UpdateRequiredScreen } from "./screens/launch";
import { Shell } from "./screens/shell";
import { CodeScreen, SignInScreen } from "./screens/sign-in";
import { SystemCheckScreen } from "./screens/system-check";

// The SP-00d spike pages are compiled into debug builds only.
const SpikeApp = import.meta.env.DEV
  ? lazy(() => import("./spikes/SpikeApp").then((module) => ({ default: module.SpikeApp })))
  : null;
const SPIKE_HASHES = ["#/media", "#/livekit"];

function useDarkTheme() {
  useEffect(() => {
    // Follow Windows' light or dark setting (the design system's `.dark` class).
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => document.documentElement.classList.toggle("dark", query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);
}

export function App() {
  useDarkTheme();
  const spike = SpikeApp && SPIKE_HASHES.some((hash) => window.location.hash.startsWith(hash));
  if (spike && SpikeApp) {
    return (
      <Suspense fallback={null}>
        <SpikeApp />
      </Suspense>
    );
  }
  return <CandidateApp />;
}

/** PRD §26 up to "Ready": version check, sign-in, interviews, system check. */
function CandidateApp() {
  const [state, dispatch] = useReducer(transition, initialState);
  const [locale, setLocale] = useState<Locale>(() => pickLocale(navigator.languages));

  const onRelease = useCallback(
    (release: ReleaseState) => dispatch({ type: "release-checked", release }),
    [],
  );
  const onSignIn = useCallback((result: SignInResult) => {
    if (result.status === "code_required") {
      dispatch({ type: "code-required", challengeId: result.challenge_id, sentTo: result.sent_to });
      return;
    }
    const { status: _, ...profile } = result;
    setLocale(pickLocale([profile.candidate.locale, ...navigator.languages]));
    dispatch({ type: "signed-in", profile });
  }, []);
  const send = useCallback((event: FlowEvent) => dispatch(event), []);
  const signOut = useCallback(async () => {
    try {
      await commands.signOut();
    } finally {
      dispatch({ type: "signed-out" });
    }
  }, []);
  const lost = useCallback((error: unknown) => {
    if (isSessionLost(error)) dispatch({ type: "session-expired" });
  }, []);

  const profile = "profile" in state ? state.profile : undefined;
  return (
    <I18nProvider locale={locale}>
      <Shell profile={profile} onSignOut={profile ? () => void signOut() : undefined}>
        {state.screen === "launch" ? <LaunchScreen onChecked={onRelease} /> : null}
        {state.screen === "update-required" ? (
          <UpdateRequiredScreen minimumVersion={state.minimumVersion} downloadUrl={state.downloadUrl} />
        ) : null}
        {state.screen === "sign-in" ? (
          <SignInScreen updateAvailable={state.updateAvailable} notice={state.notice} onResult={onSignIn} />
        ) : null}
        {state.screen === "code" ? (
          <CodeScreen
            challengeId={state.challengeId}
            sentTo={state.sentTo}
            onResult={onSignIn}
            onBack={() => send({ type: "back" })}
          />
        ) : null}
        {state.screen === "interviews" ? (
          <InterviewsScreen
            profile={state.profile}
            onStart={(interviewId) => send({ type: "check-started", interviewId })}
          />
        ) : null}
        {state.screen === "system-check" ? (
          <SystemCheckScreen
            interviewId={state.interviewId}
            onPassed={() => send({ type: "check-passed" })}
            onBack={() => send({ type: "back" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "ready" ? <ReadyScreen onBack={() => send({ type: "back" })} /> : null}
      </Shell>
      <Toaster />
    </I18nProvider>
  );
}
