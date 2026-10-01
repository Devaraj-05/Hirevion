"use client";

import { Button, Form, FormField, Input } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { signIn } from "@/auth/api";
import { safeNext } from "@/auth/next-path";
import { z } from "@/config/zod";

interface LoginFormProps {
  /** Where to go once signed in (checked: only a path on this site). */
  next: string;
  /** Navigation, injectable for tests. A full load, so the proxy sees the new cookie. */
  onSignedIn?: (target: string) => void;
}

function navigate(target: string): void {
  window.location.assign(target);
}

export function LoginForm({ next, onSignedIn = navigate }: LoginFormProps) {
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
    const result = await signIn(values.email, values.password);
    if (result.ok) {
      onSignedIn(safeNext(next));
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
        <div
          ref={alert}
          role="alert"
          tabIndex={-1}
          className="rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
        >
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
      <Link href="/forgot-password" className="text-accent text-sm hover:underline">
        {t("forgot")}
      </Link>
    </Form>
  );
}
