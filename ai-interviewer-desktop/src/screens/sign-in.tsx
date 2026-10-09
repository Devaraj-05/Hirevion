import { Button, Input, Label } from "@hirevion/ui";
import { type FormEvent, useId, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, type SignInResult } from "../native/commands";
import { type ErrorKey, errorKey } from "./errors";
import { ErrorText } from "./shell";

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
    <form noValidate onSubmit={submit} className="mx-auto grid w-full max-w-sm gap-5">
      <div className="grid gap-1">
        <h1 className="font-semibold text-2xl">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("intro")}</p>
      </div>
      {notice === "session-expired" ? (
        <p className="text-sm text-warning">{t("sessionExpired")}</p>
      ) : null}
      {updateAvailable ? (
        <p className="text-muted-foreground text-sm">{t("updateAvailable")}</p>
      ) : null}
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-email`}>{t("email")}</Label>
        <Input
          id={`${id}-email`}
          type="email"
          autoComplete="username"
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
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      <Button type="submit" disabled={working || !email.trim() || !password}>
        {working ? t("working") : t("submit")}
      </Button>
    </form>
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
    <form noValidate onSubmit={submit} className="mx-auto grid w-full max-w-sm gap-5">
      <div className="grid gap-1">
        <h1 className="font-semibold text-2xl">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("intro", { sentTo })}</p>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-code`}>{t("label")}</Label>
        <Input
          id={`${id}-code`}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
        />
      </div>
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      {resent && !error ? <p className="text-muted-foreground text-sm">{t("resent")}</p> : null}
      <Button type="submit" disabled={working || code.length !== 6}>
        {t("submit")}
      </Button>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" onClick={resend}>
          {t("resend")}
        </Button>
        <Button type="button" variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
    </form>
  );
}
