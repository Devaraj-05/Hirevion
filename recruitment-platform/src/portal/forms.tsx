"use client";

import { Button, Form, FormField, Input } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { usePasswordProblem } from "@/auth/forms/problems";
import { z } from "@/config/zod";
import { portalForgotPassword, portalSetPassword, portalSignIn } from "./api";
import { safePortalNext } from "./paths";

/**
 * The portal's sign-in and emailed-link forms (ADR-0022). They read the recruiter forms'
 * shared strings (`auth.*`) and the portal's own where they differ: candidates' passwords need
 * 12 characters (ADR-0020).
 */

export const PORTAL_MIN_PASSWORD_LENGTH = 12;

/** A full load, so the server components see the new cookie. */
function navigate(target: string): void {
  window.location.assign(target);
}

const ALERT = "rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm";

export function PortalLoginForm({
  next,
  onSignedIn = navigate,
}: {
  next: string;
  onSignedIn?: (target: string) => void;
}) {
  const t = useTranslations("auth.login");
  const schema = useMemo(
    () =>
      z.object({
        email: z.string().trim().min(1, t("emailRequired")),
        password: z.string().min(1, t("passwordRequired")),
      }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });
  const [error, setError] = useState<string | null>(null);
  const alert = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) alert.current?.focus();
  }, [error]);

  async function submit(values: z.infer<typeof schema>) {
    setError(null);
    const result = await portalSignIn(values.email, values.password);
    if (result.ok) {
      onSignedIn(safePortalNext(next));
      return;
    }
    if (result.reason === "invalid") setError(t("invalid"));
    else if (result.reason === "locked" && result.retryAfter !== null) {
      setError(t("locked", { minutes: Math.ceil(result.retryAfter / 60) }));
    } else if (result.reason === "locked") setError(t("lockedSoon"));
    else setError(t("unavailable"));
  }

  return (
    <Form form={form} onSubmit={submit} className="flex flex-col gap-4">
      {error ? (
        <div ref={alert} role="alert" tabIndex={-1} className={ALERT}>
          {error}
        </div>
      ) : null}
      <FormField
        control={form.control}
        name="email"
        label={t("email")}
        render={(field) => <Input type="email" autoComplete="username" {...field} />}
      />
      <FormField
        control={form.control}
        name="password"
        label={t("password")}
        render={(field) => <Input type="password" autoComplete="current-password" {...field} />}
      />
      <Button type="submit" disabled={form.formState.isSubmitting}>
        {t("submit")}
      </Button>
      <Link href="/forgot-password" className="text-primary text-sm underline">
        {t("forgot")}
      </Link>
    </Form>
  );
}

type ForgotOutcome = { kind: "sent"; email: string } | { kind: "limited" | "unavailable" };

export function PortalForgotForm() {
  const t = useTranslations("auth.forgot");
  const portal = useTranslations("portal.forgot");
  const schema = useMemo(
    () => z.object({ email: z.string().trim().min(1, t("emailRequired")) }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });
  const [outcome, setOutcome] = useState<ForgotOutcome | null>(null);

  async function submit({ email }: z.infer<typeof schema>) {
    const result = await portalForgotPassword(email);
    setOutcome(result === "sent" ? { kind: "sent", email } : { kind: result });
  }

  if (outcome?.kind === "sent") {
    return (
      <p role="status" className="rounded-md bg-surface-muted px-3 py-2 text-sm">
        {portal("sent", { email: outcome.email })}
      </p>
    );
  }
  return (
    <Form form={form} onSubmit={submit} className="flex flex-col gap-4">
      {outcome ? (
        <p role="alert" className={ALERT}>
          {outcome.kind === "limited" ? t("limited") : t("unavailable")}
        </p>
      ) : null}
      <FormField
        control={form.control}
        name="email"
        label={t("email")}
        render={(field) => <Input type="email" autoComplete="username" {...field} />}
      />
      <Button type="submit" disabled={form.formState.isSubmitting}>
        {t("submit")}
      </Button>
      <Link href="/login" className="text-primary text-sm underline">
        {t("back")}
      </Link>
    </Form>
  );
}

export function PortalPasswordForm({
  token,
  mode,
  onDone = navigate,
}: {
  token: string;
  /** `set`: the invitation's first password. `reset`: a forgotten one. */
  mode: "set" | "reset";
  onDone?: (target: string) => void;
}) {
  const t = useTranslations("auth.newPassword");
  const portal = useTranslations("portal.password");
  const shared = usePasswordProblem();
  const problem = (code: string) => (code === "too_short" ? portal("tooShort") : shared(code));
  const schema = useMemo(
    () =>
      z
        .object({
          password: z.string().min(PORTAL_MIN_PASSWORD_LENGTH, portal("tooShort")),
          confirmation: z.string(),
        })
        .refine((values) => values.password === values.confirmation, {
          path: ["confirmation"],
          message: t("mismatch"),
        }),
    [t, portal],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirmation: "" },
  });
  const [failure, setFailure] = useState<"expired" | "unavailable" | null>(null);

  async function submit({ password }: z.infer<typeof schema>) {
    setFailure(null);
    const result = await portalSetPassword(mode, token, password);
    if (result.ok) {
      onDone(mode === "set" ? "/login?set=1" : "/login?reset=1");
      return;
    }
    if (result.reason === "rejected") {
      form.setError("password", { message: result.codes.map(problem).join(" ") });
      return;
    }
    setFailure(result.reason);
  }

  return (
    <Form form={form} onSubmit={submit} className="flex flex-col gap-4">
      {failure ? (
        <div role="alert" className={ALERT}>
          {failure === "expired" ? (
            <>
              <p>{t("expired")}</p>
              <Link href="/forgot-password" className="font-medium underline">
                {t("askAgain")}
              </Link>
            </>
          ) : (
            <p>{t("unavailable")}</p>
          )}
        </div>
      ) : null}
      <FormField
        control={form.control}
        name="password"
        label={t("password")}
        description={portal("hint")}
        render={(field) => <Input type="password" autoComplete="new-password" {...field} />}
      />
      <FormField
        control={form.control}
        name="confirmation"
        label={t("confirmation")}
        render={(field) => <Input type="password" autoComplete="new-password" {...field} />}
      />
      <Button type="submit" disabled={form.formState.isSubmitting}>
        {mode === "reset" ? t("saveReset") : t("saveSet")}
      </Button>
    </Form>
  );
}
