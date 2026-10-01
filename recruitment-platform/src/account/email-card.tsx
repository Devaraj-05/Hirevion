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
import { changeEmail } from "@/auth/api";
import { usePasswordProblem } from "@/auth/forms/problems";
import { z } from "@/config/zod";

/** Sends a confirmation link to a new address; the email changes once it is followed. */
export function EmailCard({ email }: { email: string }) {
  const t = useTranslations("account.email");
  const problem = usePasswordProblem();
  const schema = useMemo(
    () =>
      z.object({
        newEmail: z.string().trim().min(1, t("newRequired")),
        password: z.string().min(1, t("passwordRequired")),
      }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { newEmail: "", password: "" },
  });
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  async function submit(values: z.infer<typeof schema>) {
    setUnavailable(false);
    const result = await changeEmail(values.newEmail, values.password);
    if (result.ok) {
      setSentTo(values.newEmail);
      form.reset();
    } else if (result.reason === "rejected") {
      for (const code of Object.values(result.problems)) {
        form.setError("password", { message: problem(code) });
      }
    } else {
      setUnavailable(true);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm">{t("intro", { email })}</p>
        {sentTo ? (
          <p role="status" className="rounded-md bg-success-subtle px-3 py-2 text-sm">
            {t("sent", { email: sentTo })}
          </p>
        ) : null}
        <Form form={form} onSubmit={submit} className="flex max-w-sm flex-col gap-4">
          <FormField
            control={form.control}
            name="newEmail"
            label={t("new")}
            render={(field) => <Input type="email" autoComplete="email" {...field} />}
          />
          <FormField
            control={form.control}
            name="password"
            label={t("password")}
            render={(field) => <Input type="password" autoComplete="current-password" {...field} />}
          />
          {unavailable ? (
            <p
              role="alert"
              className="rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
            >
              {t("unavailable")}
            </p>
          ) : null}
          <div>
            <Button type="submit" variant="secondary" disabled={form.formState.isSubmitting}>
              {t("submit")}
            </Button>
          </div>
        </Form>
      </CardContent>
    </Card>
  );
}
