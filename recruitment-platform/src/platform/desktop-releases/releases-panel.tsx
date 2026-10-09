"use client";

import {
  Badge,
  type BadgeTone,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  Input,
  Label,
  NativeSelect,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { useStepUp } from "@/admin/step-up";
import {
  type Channel,
  createRelease,
  getReleaseRegistry,
  type Release,
  releaseKeys,
  updateChannel,
  updateRelease,
} from "./api";

const STATUS_TONES: Record<Release["status"], BadgeTone> = {
  draft: "neutral",
  published: "success",
  withdrawn: "warning",
};

/** The desktop release registry (PRD §26, §28): each channel's minimum version, and the builds
 * with their rollout. Every change asks for the password if it wasn't confirmed recently. */
export function ReleasesPanel() {
  const t = useTranslations("platform.releases");
  const format = useFormatter();
  const problems = useAdminProblem();
  const withStepUp = useStepUp();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const registry = useQuery({ queryKey: releaseKeys.registry, queryFn: getReleaseRegistry });

  const change = useMutation({
    mutationFn: (input: { id: string; status?: Release["status"]; rollout_percent?: number }) =>
      withStepUp(() =>
        updateRelease(input.id, {
          ...(input.status ? { status: input.status } : {}),
          ...(input.rollout_percent !== undefined
            ? { rollout_percent: input.rollout_percent }
            : {}),
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.registry });
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });

  if (registry.isPending) return <Skeleton className="h-48 w-full" />;
  if (!registry.data) return <p className="text-sm">{t("loadFailed")}</p>;

  return (
    <div className="grid gap-6">
      <div className="grid gap-4 md:grid-cols-2">
        {registry.data.channels.map((channel) => (
          <ChannelCard key={channel.channel} channel={channel} />
        ))}
      </div>
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-lg">{t("releases")}</h2>
        <Button onClick={() => setAdding(true)}>{t("add")}</Button>
      </div>
      {registry.data.releases.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("caption")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                {(
                  [
                    "version",
                    "channel",
                    "arch",
                    "status",
                    "rollout",
                    "published",
                    "actions",
                  ] as const
                ).map((column) => (
                  <th key={column} scope="col" className="px-3 py-2 text-left font-medium">
                    {t(`columns.${column}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {registry.data.releases.map((release) => (
                <tr key={release.id} className="border-border border-t">
                  <td className="px-3 py-2 font-medium">{release.version}</td>
                  <td className="px-3 py-2">{release.channel}</td>
                  <td className="px-3 py-2">{release.arch}</td>
                  <td className="px-3 py-2">
                    <Badge tone={STATUS_TONES[release.status]}>
                      {t(`statuses.${release.status}`)}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">{t("percent", { value: release.rollout_percent })}</td>
                  <td className="px-3 py-2">
                    {release.published_at
                      ? format.dateTime(new Date(release.published_at), { dateStyle: "medium" })
                      : t("never")}
                  </td>
                  <td className="flex flex-wrap gap-2 px-3 py-2">
                    {release.status !== "published" ? (
                      <Button
                        size="sm"
                        disabled={change.isPending}
                        onClick={() => change.mutate({ id: release.id, status: "published" })}
                      >
                        {t("publish", { version: release.version })}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={change.isPending}
                        onClick={() => change.mutate({ id: release.id, status: "withdrawn" })}
                      >
                        {t("withdraw", { version: release.version })}
                      </Button>
                    )}
                    {release.rollout_percent < 100 ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={change.isPending}
                        onClick={() => change.mutate({ id: release.id, rollout_percent: 100 })}
                      >
                        {t("fullRollout")}
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding ? <AddReleaseDialog onClose={() => setAdding(false)} /> : null}
    </div>
  );
}

function ChannelCard({
  channel,
}: {
  channel: { channel: Channel; minimum_version: string; download_url: string };
}) {
  const t = useTranslations("platform.releases");
  const problems = useAdminProblem();
  const withStepUp = useStepUp();
  const queryClient = useQueryClient();
  const id = useId();
  const [minimum, setMinimum] = useState(channel.minimum_version);
  const [download, setDownload] = useState(channel.download_url);
  const save = useMutation({
    mutationFn: () =>
      withStepUp(() =>
        updateChannel(channel.channel, { minimum_version: minimum, download_url: download }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.registry });
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("channelTitle", { channel: channel.channel })}</CardTitle>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={submit} className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-minimum`}>{t("minimum")}</Label>
            <Input
              id={`${id}-minimum`}
              value={minimum}
              onChange={(event) => setMinimum(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">{t("minimumHint")}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-download`}>{t("download")}</Label>
            <Input
              id={`${id}-download`}
              type="url"
              value={download}
              onChange={(event) => setDownload(event.target.value)}
            />
          </div>
          <div>
            <Button type="submit" variant="secondary" disabled={save.isPending}>
              {t("saveChannel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function AddReleaseDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("platform.releases");
  const problems = useAdminProblem();
  const withStepUp = useStepUp();
  const queryClient = useQueryClient();
  const id = useId();
  const [values, setValues] = useState({
    version: "",
    channel: "stable" as Channel,
    arch: "x64" as Release["arch"],
    url: "",
    signature: "",
    notes: "",
    rollout_percent: 100,
  });
  const set = (name: keyof typeof values) => (value: string) =>
    setValues((previous) => ({
      ...previous,
      [name]: name === "rollout_percent" ? Number(value) : value,
    }));
  const save = useMutation({
    mutationFn: () => withStepUp(() => createRelease(values)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.registry });
      toast.success(t("added"), {});
      onClose();
    },
    onError: problems.show,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  const field = (name: "version" | "url", label: string, type = "text") => (
    <div className="grid gap-1.5">
      <Label htmlFor={`${id}-${name}`}>{label}</Label>
      <Input
        id={`${id}-${name}`}
        type={type}
        value={values[name]}
        onChange={(event) => set(name)(event.target.value)}
      />
    </div>
  );
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent title={t("addTitle")} description={t("addHint")} closeLabel={t("cancel")}>
        <form noValidate onSubmit={submit} className="grid gap-3">
          {field("version", t("columns.version"))}
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-channel`}>{t("columns.channel")}</Label>
              <NativeSelect
                id={`${id}-channel`}
                value={values.channel}
                onChange={(event) => set("channel")(event.target.value)}
                options={[
                  { value: "stable", label: "stable" },
                  { value: "beta", label: "beta" },
                ]}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-arch`}>{t("columns.arch")}</Label>
              <NativeSelect
                id={`${id}-arch`}
                value={values.arch}
                onChange={(event) => set("arch")(event.target.value)}
                options={[
                  { value: "x64", label: "x64" },
                  { value: "arm64", label: "arm64" },
                ]}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-rollout`}>{t("columns.rollout")}</Label>
              <Input
                id={`${id}-rollout`}
                type="number"
                min={0}
                max={100}
                value={values.rollout_percent}
                onChange={(event) => set("rollout_percent")(event.target.value)}
              />
            </div>
          </div>
          {field("url", t("url"), "url")}
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-signature`}>{t("signature")}</Label>
            <Textarea
              id={`${id}-signature`}
              rows={3}
              value={values.signature}
              onChange={(event) => set("signature")(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-notes`}>{t("notes")}</Label>
            <Textarea
              id={`${id}-notes`}
              rows={3}
              value={values.notes}
              onChange={(event) => set("notes")(event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {t("addSubmit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
