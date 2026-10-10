import { Toaster } from "@hirevion/ui";
import { lazy, Suspense, useCallback, useEffect, useReducer, useState } from "react";
import { type FlowEvent, initialState, transition } from "./flow/flow";
import { I18nProvider, type Locale, pickLocale } from "./i18n/i18n";
import {
  type Briefing,
  commands,
  type ReleaseState,
  type SignInResult,
  type StartResult,
} from "./native/commands";
import { BriefingScreen, ConsentScreen } from "./screens/briefing";
import { isSessionLost } from "./screens/errors";
import { CompletedScreen, InterviewScreen } from "./screens/interview";
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

/** PRD §26: version check, sign-in, interviews, briefing, system check, consent, ready, interview. */
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
  // What one interview's steps hand to the next: the briefing, the check and consent ids,
  // and the start answer (the LiveKit join for the interview screen).
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [checkId, setCheckId] = useState("");
  const [consentId, setConsentId] = useState("");
  const [started, setStarted] = useState<StartResult | null>(null);

  const profile = "profile" in state ? state.profile : undefined;
  return (
    <I18nProvider locale={locale}>
      <Shell profile={profile} onSignOut={profile ? () => void signOut() : undefined}>
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
        {state.screen === "briefing" ? (
          <BriefingScreen
            interviewId={state.interviewId}
            onRead={(read) => {
              setBriefing(read);
              send({ type: "briefing-read" });
            }}
            onBack={() => send({ type: "back" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "system-check" ? (
          <SystemCheckScreen
            interviewId={state.interviewId}
            onPassed={(id) => {
              setCheckId(id);
              send({ type: "check-passed" });
            }}
            onBack={() => send({ type: "back" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "consent" && briefing ? (
          <ConsentScreen
            interviewId={state.interviewId}
            briefing={briefing}
            onConsented={(id) => {
              setConsentId(id);
              send({ type: "consented" });
            }}
            onBack={() => send({ type: "back" })}
            onError={lost}
          />
        ) : null}
        {state.screen === "ready" ? (
          <ReadyScreen
            interviewId={state.interviewId}
            systemCheckId={checkId}
            consentId={consentId}
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
