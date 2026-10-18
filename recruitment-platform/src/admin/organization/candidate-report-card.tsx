"use client";

import { Button, Card, CardContent, CardHeader, CardTitle, Skeleton, toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { getReportSettings, ITEM_KEYS, reportKeys, saveReportSettings } from "@/reports/api";

/** Which of PRD §99's five items recruiters may release to a candidate. The organisation chooses
 * here; a recruiter still approves each release. */
export function CandidateReportCard() {
  const t = useTranslations("admin.organization.candidateReport");
  const items = useTranslations("reports.candidateVisible.items");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: reportKeys.settings, queryFn: getReportSettings });
  const [draft, setDraft] = useState<Record<string, boolean> | null>(null);
  useEffect(() => {
    if (settings.data && draft === null) setDraft(settings.data);
  }, [settings.data, draft]);
  const save = useMutation({
    mutationFn: (value: Record<string, boolean>) => saveReportSettings(value),
    onSuccess: (saved) => {
      queryClient.setQueryData(reportKeys.settings, saved);
      setDraft(saved);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-muted-foreground text-sm">{t("hint")}</p>
        {draft === null ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <form
            noValidate
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate(draft);
            }}
          >
            <fieldset className="grid gap-1">
              <legend className="sr-only">{t("title")}</legend>
              {ITEM_KEYS.map((key) => (
                // Rows tall enough that each checkbox has the 24 px of clear space WCAG 2.2 asks for.
                <label key={key} className="flex min-h-8 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft[key] ?? false}
                    onChange={(event) => setDraft({ ...draft, [key]: event.target.checked })}
                  />
                  {items(key)}
                </label>
              ))}
            </fieldset>
            <div>
              <Button type="submit" disabled={save.isPending}>
                {t("save")}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
