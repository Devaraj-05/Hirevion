import { Toaster } from "@hirevion/ui";
import { lazy, Suspense, useCallback, useEffect, useReducer, useState } from "react";
import { type FlowEvent, initialState, transition } from "./flow/flow";
import { I18nProvider, type Locale, pickLocale } from "./i18n/i18n";
import {
  commands,
  type ReleaseState,
  type SignInResult,
  type StartResult,
} from "./native/commands";
import { isSessionLost } from "./screens/errors";
import { CompletedScreen, InterviewScreen } from "./screens/interview";
import { InterviewsScreen } from "./screens/interviews";
import { LaunchScreen, UpdateRequiredScreen } from "./screens/launch";
import { PrepareScreen } from "./screens/prepare";
import { Shell } from "./screens/shell";
import { CodeScreen, SignInScreen } from "./screens/sign-in";

// The SP-00d spike pages are compiled into debug builds only.
const SpikeApp = import.meta.env.DEV
  ? lazy(() => import("./spikes/SpikeApp").then((module) => ({ default: module.SpikeApp })))
  : null;
const SPIKE_HASHES = ["#/media", "#/livekit"];
// The interview's looks, state by state, for checking them by eye and in Playwright.
const Gallery = import.meta.env.DEV
  ? lazy(() => import("./spikes/gallery").then((module) => ({ default: module.Gallery })))
  : null;

function useDarkTheme() {
  useEffect(() => {
    // Follow Windows' light or dark setting: the design system switches every token on
    // `data-theme` (a `.dark` class, used until 2026-11-16, switched nothing).
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = query.matches ? "dark" : "light";
    };
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
  if (Gallery && window.location.hash.startsWith("#/gallery")) {
    return (
      <Suspense fallback={null}>
        <I18nProvider locale="en-US">
          <Gallery />
        </I18nProvider>
      </Suspense>
    );
  }
  return <CandidateApp />;
}

/** PRD §26: version check, sign-in, interviews, the page before the interview, the interview. */
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
  // The start answer (the LiveKit join) for the interview screen.
  const [started, setStarted] = useState<StartResult | null>(null);

  const profile = "profile" in state ? state.profile : undefined;
  return (
    <I18nProvider locale={locale}>
      <Shell
        profile={profile}
        onSignOut={profile ? () => void signOut() : undefined}
        immersive={state.screen === "interview"}
      >
        {state.screen === "launch" ? <LaunchScreen onChecked={onRelease} /> : null}
        {state.screen === "update-required" ? (
          <UpdateRequiredScreen
            minimumVersion={state.minimumVersion}
            downloadUrl={state.downloadUrl}
          />
        ) : null}
        {state.screen === "sign-in" ? (
          <SignInScreen
            updateAvailable={state.updateAvailable}
            notice={state.notice}
            onResult={onSignIn}
          />
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
            onStart={(interviewId) => send({ type: "interview-chosen", interviewId })}
          />
        ) : null}
        {state.screen === "prepare" ? (
          <PrepareScreen
            interviewId={state.interviewId}
            summary={state.profile.interviews.find((one) => one.id === state.interviewId)}
            onStarted={(start) => {
              setStarted(start);
              send({ type: "started" });
            }}
            onBack={() => send({ type: "back" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "interview" && started ? (
          <InterviewScreen
            interviewId={state.interviewId}
            start={started}
            onCompleted={() => send({ type: "completed" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "completed" ? (
          <CompletedScreen onBack={() => send({ type: "back" })} />
        ) : null}
      </Shell>
      <Toaster theme="system" />
    </I18nProvider>
  );
}
