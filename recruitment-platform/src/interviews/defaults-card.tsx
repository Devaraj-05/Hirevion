"use client";

import { Button, Skeleton, toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { getInterviewDefaults, type InterviewDefaults, saveInterviewDefaults } from "./api";
import { SettingsFields, settingsBody, settingsOf, settingsProblems } from "./settings-fields";
import { keys } from "./template-form";

/** The organisation's interview defaults, on the organisation profile page: new templates start
 * from them; existing templates keep their own settings. */
export function InterviewDefaultsCard() {
  const t = useTranslations("interviews.defaults");
  const defaults = useQuery({ queryKey: keys.defaults, queryFn: getInterviewDefaults });
  return (
    <section className="grid gap-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold text-base">{t("title")}</h2>
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      {defaults.data ? (
        <DefaultsForm key={JSON.stringify(defaults.data)} value={defaults.data} />
      ) : (
        <Skeleton className="h-48 w-full" />
      )}
    </section>
  );
}

function DefaultsForm({ value }: { value: InterviewDefaults }) {
  const t = useTranslations("interviews.defaults");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const [settings, setSettings] = useState(() => settingsOf(value));
  const [tried, setTried] = useState(false);
  const save = useMutation({
    mutationFn: () => saveInterviewDefaults(settingsBody(settings)),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.defaults, saved);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setTried(true);
    if (Object.keys(settingsProblems(settings)).length === 0) save.mutate();
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-5">
      <SettingsFields
        value={settings}
        onChange={setSettings}
        showProblems={tried}
        presets={value.proctoring_presets}
      />
      <Button type="submit" className="w-fit" disabled={save.isPending}>
        {t("save")}
      </Button>
    </form>
  );
}
