"use client";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Form,
  FormField,
  Input,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { changePassword } from "@/auth/api";
import { MIN_PASSWORD_LENGTH } from "@/auth/forms/new-password-form";
import { usePasswordProblem } from "@/auth/forms/problems";
import { z } from "@/config/zod";

const FIELDS: Record<string, "current" | "password"> = {
  current_password: "current",
  new_password: "password",
};

/** Changes the password; the user's other devices are signed out. */
export function PasswordCard({ email }: { email: string }) {
  const t = useTranslations("account.password");
  const labels = useTranslations("auth.newPassword");
  const problem = usePasswordProblem();
  const schema = useMemo(
    () =>
      z
        .object({
          current: z.string().min(1, t("currentRequired")),
          password: z.string().min(MIN_PASSWORD_LENGTH, problem("too_short")),
          confirmation: z.string(),
        })
        .refine((values) => values.password === values.confirmation, {
          path: ["confirmation"],
          message: labels("mismatch"),
        }),
    [t, labels, problem],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { current: "", password: "", confirmation: "" },
  });
  const [outcome, setOutcome] = useState<"done" | "unavailable" | null>(null);

  async function submit(values: z.infer<typeof schema>) {
    setOutcome(null);
    const result = await changePassword(values.current, values.password);
    if (result.ok) {
      form.reset();
      setOutcome("done");
    } else if (result.reason === "rejected") {
      for (const [field, code] of Object.entries(result.problems)) {
        form.setError(FIELDS[field] ?? "password", { message: problem(code) });
      }
    } else {
      setOutcome("unavailable");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <Form form={form} onSubmit={submit} className="flex max-w-sm flex-col gap-4">
          {/* Lets password managers save the new password against the right account. */}
          <input type="email" autoComplete="username" value={email} readOnly hidden />
          <FormField
            control={form.control}
            name="current"
            label={t("current")}
            render={(field) => <Input type="password" autoComplete="current-password" {...field} />}
          />
          <FormField
            control={form.control}
            name="password"
            label={labels("password")}
            description={labels("hint")}
            render={(field) => <Input type="password" autoComplete="new-password" {...field} />}
          />
          <FormField
            control={form.control}
            name="confirmation"
            label={labels("confirmation")}
            render={(field) => <Input type="password" autoComplete="new-password" {...field} />}
          />
          {outcome ? (
            <p
              role={outcome === "done" ? "status" : "alert"}
              className={
                outcome === "done"
                  ? "rounded-md bg-success-subtle px-3 py-2 text-sm"
                  : "rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
              }
            >
              {outcome === "done" ? t("done") : t("unavailable")}
            </p>
          ) : null}
          <div>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {t("submit")}
            </Button>
          </div>
        </Form>
      </CardContent>
    </Card>
  );
}
