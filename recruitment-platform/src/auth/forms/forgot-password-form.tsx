"use client";

import { Button, Form, FormField, Input } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { requestPasswordReset } from "@/auth/api";
import { z } from "@/config/zod";

type Outcome = { kind: "sent"; email: string } | { kind: "limited" } | { kind: "unavailable" };

/** Asks for a reset link. The answer is the same whether or not the account exists. */
export function ForgotPasswordForm() {
  const t = useTranslations("auth.forgot");
  const schema = useMemo(
    () => z.object({ email: z.string().trim().min(1, t("emailRequired")) }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  async function submit({ email }: z.infer<typeof schema>) {
    const result = await requestPasswordReset(email);
    setOutcome(result === "sent" ? { kind: "sent", email } : { kind: result });
  }

  if (outcome?.kind === "sent") {
    return (
      <p role="status" className="rounded-md bg-surface-muted px-3 py-2 text-sm">
        {t("sent", { email: outcome.email })}
      </p>
    );
  }
  return (
    <Form form={form} onSubmit={submit} className="flex flex-col gap-4">
      {outcome ? (
        <p
          role="alert"
          className="rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
        >
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
    </Form>
  );
}
