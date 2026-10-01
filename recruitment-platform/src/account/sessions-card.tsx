"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { listSessions, revokeOtherSessions, revokeSession, type SessionItem } from "@/auth/api";
import { useProblemToast } from "@/data/problems";
import { describeDevice } from "./device";

const SESSIONS = ["auth", "sessions"] as const;

/** Where the user is signed in, with sign-out per device and everywhere else. */
export function SessionsCard() {
  const t = useTranslations("account.sessions");
  const format = useFormatter();
  const showProblem = useProblemToast();
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: SESSIONS, queryFn: listSessions });
  const refresh = () => queryClient.invalidateQueries({ queryKey: SESSIONS });
  const revokeOne = useMutation({
    mutationFn: revokeSession,
    onSuccess: refresh,
    onError: showProblem,
  });
  const revokeOthers = useMutation({
    mutationFn: revokeOtherSessions,
    onSuccess: refresh,
    onError: showProblem,
  });

  const device = (session: SessionItem) => {
    const known = describeDevice(session.user_agent);
    return known
      ? t("deviceOn", { browser: known.browser, system: known.system })
      : t("unknownDevice");
  };
  const others = (sessions.data ?? []).filter((session) => !session.current).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-muted-foreground text-sm">{t("intro")}</p>
        {sessions.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : sessions.isError ? (
          <p role="alert" className="text-danger text-sm">
            {t("loadFailed")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t("caption")}</caption>
              <thead className="text-muted-foreground">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    {t("device")}
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    {t("ip")}
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    {t("lastActive")}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    <span className="sr-only">{t("actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sessions.data.map((session) => (
                  <tr key={session.id} className="border-border border-t">
                    <td className="py-2 pr-4">{device(session)}</td>
                    <td className="py-2 pr-4">{session.ip ?? t("unknownIp")}</td>
                    <td className="py-2 pr-4">
                      {format.relativeTime(new Date(session.last_seen_at))}
                    </td>
                    <td className="py-2 text-right">
                      {session.current ? (
                        <Badge tone="accent">{t("thisDevice")}</Badge>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={t("signOutDevice", { device: device(session) })}
                          onClick={() => revokeOne.mutate(session.id)}
                          disabled={revokeOne.isPending}
                        >
                          {t("signOut")}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div>
          <Button
            variant="secondary"
            onClick={() => revokeOthers.mutate()}
            disabled={others === 0 || revokeOthers.isPending}
          >
            {t("signOutOthers")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
