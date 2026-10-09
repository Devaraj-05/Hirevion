"use client";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Label,
  Skeleton,
  Switch,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { getCandidateAccess, saveCandidateAccess } from "@/admin/api";
import { useAdminProblem } from "@/admin/problems";

const KEY = ["organization", "candidate-access"] as const;

/** Whether candidates confirm a new computer with an emailed code (SP-07c). */
export function CandidateAccessCard() {
  const t = useTranslations("admin.organization.candidateAccess");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const settings = useQuery({ queryKey: KEY, queryFn: getCandidateAccess });
  const save = useMutation({
    mutationFn: (newDeviceOtp: boolean) => saveCandidateAccess(newDeviceOtp),
    onSuccess: (saved) => {
      queryClient.setQueryData(KEY, saved);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {settings.data ? (
          <div className="flex items-start gap-3">
            <Switch
              id={`${id}-otp`}
              checked={settings.data.new_device_otp}
              disabled={save.isPending}
              onCheckedChange={(checked) => save.mutate(checked)}
              aria-describedby={`${id}-hint`}
            />
            <div className="grid gap-1">
              <Label htmlFor={`${id}-otp`}>{t("newDeviceOtp")}</Label>
              <p id={`${id}-hint`} className="text-muted-foreground text-sm">
                {t("newDeviceOtpHint")}
              </p>
            </div>
          </div>
        ) : settings.isError ? (
          <div className="grid justify-items-start gap-2">
            <p className="text-sm" role="alert">
              {t("loadFailed")}
            </p>
            <Button size="sm" variant="secondary" onClick={() => void settings.refetch()}>
              {t("retry")}
            </Button>
          </div>
        ) : (
          <Skeleton className="h-10 w-full" />
        )}
      </CardContent>
    </Card>
  );
}
