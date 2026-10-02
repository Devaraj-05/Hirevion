"use client";

import { isApiProblem } from "@hirevion/api-client";
import { Button, Dialog, DialogContent, Form, FormField, Input } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { stepUp } from "@/auth/api";
import { z } from "@/config/zod";

/**
 * Step-up (ADR-0014): role changes, invitations and other sensitive changes are refused with
 * `step-up-required` unless the password was confirmed in the last few minutes. `useStepUp()`
 * wraps such a call: on that refusal it asks for the password, then tries the call once more.
 */

type WithStepUp = <T>(call: () => Promise<T>) => Promise<T>;

interface Pending {
  confirmed: () => void;
  cancelled: () => void;
}

const StepUpContext = createContext<WithStepUp | null>(null);

export function useStepUp(): WithStepUp {
  const withStepUp = useContext(StepUpContext);
  if (!withStepUp) throw new Error("useStepUp needs a StepUpProvider");
  return withStepUp;
}

export function StepUpProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);

  const withStepUp = useCallback<WithStepUp>(async (call) => {
    try {
      return await call();
    } catch (error) {
      if (!isApiProblem(error) || error.code !== "step-up-required") throw error;
      await new Promise<void>((resolve, reject) =>
        setPending({ confirmed: resolve, cancelled: () => reject(error) }),
      );
      return await call();
    }
  }, []);

  return (
    <StepUpContext.Provider value={withStepUp}>
      {children}
      {pending ? (
        <StepUpDialog
          onConfirmed={() => {
            pending.confirmed();
            setPending(null);
          }}
          onCancelled={() => {
            pending.cancelled();
            setPending(null);
          }}
        />
      ) : null}
    </StepUpContext.Provider>
  );
}

function StepUpDialog({
  onConfirmed,
  onCancelled,
}: {
  onConfirmed: () => void;
  onCancelled: () => void;
}) {
  const t = useTranslations("stepUp");
  const schema = useMemo(
    () => z.object({ password: z.string().min(1, t("passwordRequired")) }),
    [t],
  );
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { password: "" },
  });
  const [failure, setFailure] = useState<string | null>(null);

  async function submit(values: z.infer<typeof schema>) {
    setFailure(null);
    const result = await stepUp(values.password);
    if (result.ok) {
      onConfirmed();
    } else if (result.reason === "wrong") {
      form.setError("password", { message: t("wrong") });
    } else if (result.reason === "locked") {
      setFailure(
        result.retryAfter === null
          ? t("lockedSoon")
          : t("locked", { minutes: Math.max(1, Math.ceil(result.retryAfter / 60)) }),
      );
    } else {
      setFailure(t("unavailable"));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancelled())}>
      <DialogContent title={t("title")} description={t("description")} closeLabel={t("close")}>
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="password"
            label={t("password")}
            render={(field) => (
              <Input type="password" autoComplete="current-password" autoFocus {...field} />
            )}
          />
          {failure ? (
            <p role="alert" className="text-danger text-sm">
              {failure}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancelled}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {t("confirm")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
