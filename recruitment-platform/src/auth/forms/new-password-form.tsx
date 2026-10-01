"use client";

import { Button, Form, FormField, Input } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { setNewPassword } from "@/auth/api";
import { z } from "@/config/zod";
import { usePasswordProblem } from "./problems";

/** The API's minimum until MFA arrives (NIST SP 800-63B-4 for single-factor passwords). */
export const MIN_PASSWORD_LENGTH = 15;

interface NewPasswordFormProps {
  token: string;
  /** `reset`: a forgotten password. `set`: an invited user's first password. */
  mode: "reset" | "set";
  onDone?: (target: string) => void;
}

function navigate(target: string): void {
  window.location.assign(target);
}

export function NewPasswordForm({ token, mode, onDone = navigate }: NewPasswordFormProps) {
  const t = useTranslations("auth.newPassword");
  const problem = usePasswordProblem();
  const schema = useMemo(
    () =>
      z
        .object({
          password: z.string().min(MIN_PASSWORD_LENGTH, problem("too_short")),
          confirmation: z.string(),
        })
        .refine((values) => values.password === values.confirmation, {
          path: ["confirmation"],
          message: t("mismatch"),
        }),
    [t, problem],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirmation: "" },
  });
  const [failure, setFailure] = useState<"expired" | "unavailable" | null>(null);

  async function submit({ password }: z.infer<typeof schema>) {
    setFailure(null);
    const result = await setNewPassword(mode, token, password);
    if (result.ok) {
      onDone(mode === "reset" ? "/login?reset=1" : "/login?set=1");
      return;
    }
    if (result.reason === "rejected") {
      for (const code of Object.values(result.problems)) {
        form.setError("password", { message: problem(code) });
      }
      return;
    }
    setFailure(result.reason);
  }

  return (
    <Form form={form} onSubmit={submit} className="flex flex-col gap-4">
      {failure ? (
        <div
          role="alert"
          className="rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
        >
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
        description={t("hint")}
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
