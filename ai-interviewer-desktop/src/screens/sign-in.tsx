import { Input, Label } from "@hirevion/ui";
import { type FormEvent, useId, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, type SignInResult } from "../native/commands";
import { Notice, Panel, PillButton, ScreenTitle } from "../ui/kit";
import { type ErrorKey, errorKey } from "./errors";

const FIELD = "h-11 rounded-xl px-3.5 text-[0.95rem]";

/** Email and password from the invitation (PRD §28). The API checks the six items. */
export function SignInScreen({
  updateAvailable,
  notice,
  onResult,
}: {
  updateAvailable: boolean;
  notice?: "session-expired" | undefined;
  onResult: (result: SignInResult) => void;
}) {
  const t = useTranslations("signIn");
  const errors = useTranslations("errors");
  const id = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim() || !password) return;
    setWorking(true);
    setError(null);
    try {
      onResult(await commands.signIn(email.trim(), password));
    } catch (failure) {
      setError(errorKey(failure));
      setPassword("");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="m-auto w-full max-w-[25rem]">
      <Panel className="p-8">
        <form noValidate onSubmit={submit} className="grid gap-6">
          <ScreenTitle title={t("title")} lead={t("intro")} />
          {notice === "session-expired" ? <Notice>{t("sessionExpired")}</Notice> : null}
          {updateAvailable ? <Notice tone="accent">{t("updateAvailable")}</Notice> : null}
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-email`}>{t("email")}</Label>
              <Input
                id={`${id}-email`}
                type="email"
                autoComplete="username"
                className={FIELD}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-password`}>{t("password")}</Label>
              <Input
                id={`${id}-password`}
                type="password"
                autoComplete="current-password"
                className={FIELD}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          </div>
          {error ? (
            <Notice role="alert" tone="danger">
              {errors(error)}
            </Notice>
          ) : null}
          <PillButton
            type="submit"
            size="lg"
            className="w-full"
            disabled={working || !email.trim() || !password}
          >
            {working ? t("working") : t("submit")}
          </PillButton>
        </form>
      </Panel>
    </div>
  );
}

/** The emailed code a new device needs (one-time code, org setting; contract candidate-auth). */
export function CodeScreen({
  challengeId,
  sentTo,
  onResult,
  onBack,
}: {
  challengeId: string;
  sentTo: string;
  onResult: (result: SignInResult) => void;
  onBack: () => void;
}) {
  const t = useTranslations("code");
  const errors = useTranslations("errors");
  const id = useId();
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [resent, setResent] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!/^\d{6}$/.test(code)) return;
    setWorking(true);
    setError(null);
    try {
      onResult(await commands.verifyCode(challengeId, code));
    } catch (failure) {
      const key = errorKey(failure);
      if (key === "otp-attempts-exceeded") onBack();
      setError(key);
    } finally {
      setWorking(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      await commands.resendCode(challengeId);
      setResent(true);
    } catch (failure) {
      setError(errorKey(failure));
    }
  }

  return (
    <div className="m-auto w-full max-w-[25rem]">
      <Panel className="p-8">
        <form noValidate onSubmit={submit} className="grid gap-6">
          <ScreenTitle title={t("title")} lead={t("intro", { sentTo })} />
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-code`}>{t("label")}</Label>
            <Input
              id={`${id}-code`}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              className={`${FIELD} text-center font-medium text-xl tabular-nums tracking-[0.5em]`}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            />
          </div>
          {error ? (
            <Notice role="alert" tone="danger">
              {errors(error)}
            </Notice>
          ) : null}
          {resent && !error ? <Notice tone="success">{t("resent")}</Notice> : null}
          <PillButton
            type="submit"
            size="lg"
            className="w-full"
            disabled={working || code.length !== 6}
          >
            {t("submit")}
          </PillButton>
          <div className="flex flex-wrap justify-center gap-1">
            <PillButton type="button" variant="quiet" onClick={resend}>
              {t("resend")}
            </PillButton>
            <PillButton type="button" variant="quiet" onClick={onBack}>
              {t("back")}
            </PillButton>
          </div>
        </form>
      </Panel>
    </div>
  );
}
