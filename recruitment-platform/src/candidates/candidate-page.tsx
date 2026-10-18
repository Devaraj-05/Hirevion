"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@hirevion/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, SearchX } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { type Candidate, downloadHref, getCandidate } from "./api";
import {
  AiInterviewTab,
  ApplicationStatusAction,
  CodingTab,
  InterviewHistoryTab,
  NotesTab,
  ProctoringTab,
  RecordingsTab,
  ReportsTab,
  ScreeningTab,
  SkillsTab,
  TimelineTab,
  useCandidate360,
} from "./candidate-360";
import { FlagWarnings } from "./flags";
import { keys } from "./queries";

/** Where an item came from in the resume (ADR-0015's evidence). */
interface Evidence {
  quote: string;
  page?: number | null;
  section?: string | null;
}
interface Quoted extends Evidence {
  value: string;
}
interface Profile {
  email?: Quoted | null;
  phone?: Quoted | null;
  location?: Quoted | null;
  summary?: Quoted | null;
  total_experience_years?: number | null;
  skills?: (Evidence & { name: string; years?: number | null })[];
  positions?: (Evidence & {
    company?: string | null;
    title?: string | null;
    start?: string | null;
    end?: string | null;
    current?: boolean;
  })[];
  education?: (Evidence & {
    institution?: string | null;
    degree?: string | null;
    field?: string | null;
    end?: string | null;
  })[];
  certifications?: (Evidence & { name: string; issuer?: string | null; year?: string | null })[];
  projects?: (Evidence & { name: string; description?: string | null })[];
  achievements?: (Evidence & { text: string })[];
  languages?: (Evidence & { name: string })[];
  links?: (Evidence & { url: string })[];
}

const SAFE_LINK = /^https?:\/\//i;

/** One candidate (PRD §19–20): Candidate 360's thirteen tabs. Profile, Resume and Applications
 * come from the candidate; the others from `GET /candidates/{id}/360`, and a tab the reader's
 * permissions don't cover isn't shown. `canManage` adds the status action to the applications. */
export function CandidatePage({ id, canManage = false }: { id: string; canManage?: boolean }) {
  const t = useTranslations("candidates");
  const titles = useTranslations("routes");
  const candidate = useQuery({ queryKey: keys.candidate(id), queryFn: () => getCandidate(id) });
  const overview = useCandidate360(id);
  const placeholderTitle = <h1 className="sr-only">{titles("candidatesDetail")}</h1>;

  if (candidate.isPending) {
    return (
      <>
        {placeholderTitle}
        <Skeleton className="h-64 w-full" />
      </>
    );
  }
  if (candidate.isError) {
    const missing = isApiProblem(candidate.error) && candidate.error.status === 404;
    return (
      <>
        {placeholderTitle}
        <EmptyState
          icon={<SearchX />}
          title={missing ? t("page.notFound") : t("page.loadFailed")}
          action={
            <Button asChild variant="secondary">
              <Link href="/candidates">{t("page.back")}</Link>
            </Button>
          }
        />
      </>
    );
  }

  const current = candidate.data;
  const access = overview.data?.access;
  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/candidates"
        className="flex w-fit items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("page.back")}
      </Link>
      <div className="grid gap-1">
        <h1 className="font-semibold text-2xl tracking-tight">{current.name}</h1>
        <p className="text-muted-foreground text-sm">
          {[current.headline, current.location].filter(Boolean).join(" · ")}
        </p>
      </div>
      <FlagWarnings flags={current.flags} label={t("page.warnings")} />
      <Tabs defaultValue="profile">
        <TabsList label={current.name} className="flex-wrap">
          <TabsTrigger value="profile">{t("page.tabs.profile")}</TabsTrigger>
          <TabsTrigger value="resumes">{t("page.tabs.resumes")}</TabsTrigger>
          <TabsTrigger value="applications">{t("page.tabs.applications")}</TabsTrigger>
          {overview.data ? (
            <>
              <TabsTrigger value="screening">{t("page.tabs.screening")}</TabsTrigger>
              {access?.interviews ? (
                <TabsTrigger value="history">{t("page.tabs.history")}</TabsTrigger>
              ) : null}
              <TabsTrigger value="skills">{t("page.tabs.skills")}</TabsTrigger>
              {access?.interviews ? (
                <>
                  <TabsTrigger value="coding">{t("page.tabs.coding")}</TabsTrigger>
                  <TabsTrigger value="ai">{t("page.tabs.ai")}</TabsTrigger>
                </>
              ) : null}
              {access?.proctoring ? (
                <TabsTrigger value="proctoring">{t("page.tabs.proctoring")}</TabsTrigger>
              ) : null}
              {access?.recordings ? (
                <TabsTrigger value="recordings">{t("page.tabs.recordings")}</TabsTrigger>
              ) : null}
              {access?.reports || access?.interviews ? (
                <TabsTrigger value="reports">{t("page.tabs.reports")}</TabsTrigger>
              ) : null}
              <TabsTrigger value="notes">{t("page.tabs.notes")}</TabsTrigger>
              <TabsTrigger value="timeline">{t("page.tabs.timeline")}</TabsTrigger>
            </>
          ) : null}
        </TabsList>
        <TabsContent value="profile">
          <ProfileView candidate={current} />
        </TabsContent>
        <TabsContent value="resumes">
          <Documents candidate={current} />
        </TabsContent>
        <TabsContent value="applications">
          <Applications candidate={current} canManage={canManage} />
        </TabsContent>
        {overview.data ? (
          <>
            <TabsContent value="screening">
              <ScreeningTab data={overview.data} />
            </TabsContent>
            <TabsContent value="history">
              <InterviewHistoryTab data={overview.data} />
            </TabsContent>
            <TabsContent value="skills">
              <SkillsTab data={overview.data} />
            </TabsContent>
            <TabsContent value="coding">
              <CodingTab data={overview.data} />
            </TabsContent>
            <TabsContent value="ai">
              <AiInterviewTab data={overview.data} />
            </TabsContent>
            <TabsContent value="proctoring">
              <ProctoringTab data={overview.data} />
            </TabsContent>
            <TabsContent value="recordings">
              <RecordingsTab data={overview.data} />
            </TabsContent>
            <TabsContent value="reports">
              <ReportsTab data={overview.data} />
            </TabsContent>
            <TabsContent value="notes">
              <NotesTab data={overview.data} />
            </TabsContent>
            <TabsContent value="timeline">
              <TimelineTab candidateId={id} />
            </TabsContent>
          </>
        ) : null}
      </Tabs>
    </div>
  );
}

function Quote({ evidence }: { evidence: Evidence }) {
  const t = useTranslations("candidates.profile");
  return (
    <span className="block text-muted-foreground text-xs">
      {evidence.page
        ? t("evidence", { page: evidence.page, quote: evidence.quote })
        : t("evidenceNoPage", { quote: evidence.quote })}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-2 rounded-lg border border-border p-4">
      <h2 className="font-semibold text-base">{title}</h2>
      {children}
    </section>
  );
}

function Items<T extends Evidence>({
  title,
  items,
  render,
}: {
  title: string;
  items: T[] | undefined;
  render: (item: T) => ReactNode;
}) {
  if (!items || items.length === 0) return null;
  return (
    <Section title={title}>
      <ul className="grid gap-3">
        {items.map((item) => (
          <li key={`${item.quote}-${item.page ?? 0}`}>
            {render(item)}
            <Quote evidence={item} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function ProfileView({ candidate }: { candidate: Candidate }) {
  const t = useTranslations("candidates.profile");
  const profile = candidate.profile as Profile;
  const contact = (["email", "phone", "location"] as const).flatMap((field) => {
    const item = profile[field];
    return item ? [{ field, item }] : [];
  });
  const range = (start?: string | null, end?: string | null, current?: boolean) =>
    [start, current ? t("current") : end].filter(Boolean).join(" – ");

  return (
    <div className="grid max-w-3xl gap-4">
      {contact.length > 0 ? (
        <Section title={t("contact")}>
          <dl className="grid gap-2">
            {contact.map(({ field, item }) => (
              <div key={field}>
                <dt className="text-muted-foreground text-xs">{t(field)}</dt>
                <dd>
                  {item.value}
                  <Quote evidence={item} />
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      ) : null}
      {profile.summary ? (
        <Section title={t("summary")}>
          <p>{profile.summary.value}</p>
          <Quote evidence={profile.summary} />
        </Section>
      ) : null}
      {profile.total_experience_years ? (
        <p className="text-sm">{t("totalExperience", { years: profile.total_experience_years })}</p>
      ) : null}
      <Items
        title={t("skills")}
        items={profile.skills}
        render={(skill) => (
          <span className="font-medium">
            {skill.name}
            {skill.years ? ` · ${t("years", { years: skill.years })}` : null}
          </span>
        )}
      />
      <Items
        title={t("experience")}
        items={profile.positions}
        render={(position) => (
          <div>
            <div className="font-medium">
              {[position.title, position.company].filter(Boolean).join(", ")}
            </div>
            <div className="text-muted-foreground text-sm">
              {range(position.start, position.end, position.current)}
            </div>
          </div>
        )}
      />
      <Items
        title={t("education")}
        items={profile.education}
        render={(school) => (
          <div>
            <div className="font-medium">
              {[school.degree, school.field].filter(Boolean).join(", ")}
            </div>
            <div className="text-muted-foreground text-sm">
              {[school.institution, school.end].filter(Boolean).join(", ")}
            </div>
          </div>
        )}
      />
      <Items
        title={t("certifications")}
        items={profile.certifications}
        render={(item) => (
          <span className="font-medium">
            {[item.name, item.issuer, item.year].filter(Boolean).join(", ")}
          </span>
        )}
      />
      <Items
        title={t("projects")}
        items={profile.projects}
        render={(item) => (
          <div>
            <div className="font-medium">{item.name}</div>
            {item.description ? <div className="text-sm">{item.description}</div> : null}
          </div>
        )}
      />
      <Items title={t("achievements")} items={profile.achievements} render={(item) => item.text} />
      <Items title={t("languages")} items={profile.languages} render={(item) => item.name} />
      <Items
        title={t("links")}
        items={profile.links}
        render={(item) =>
          SAFE_LINK.test(item.url) ? (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="break-all underline"
            >
              {item.url}
            </a>
          ) : (
            <span className="break-all">{item.url}</span>
          )
        }
      />
    </div>
  );
}

function Documents({ candidate }: { candidate: Candidate }) {
  const t = useTranslations("candidates.documents");
  const statuses = useTranslations("jobs.resumes.statuses");
  const format = useFormatter();
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <caption className="sr-only">{t("caption")}</caption>
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("file")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("status")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("uploaded")}
            </th>
          </tr>
        </thead>
        <tbody>
          {candidate.documents.map((document) => {
            const name = document.filename ?? t("unnamed");
            return (
              <tr key={document.id} className="border-border border-t">
                <td className="px-3 py-2">
                  {document.status === "quarantined" ? (
                    name
                  ) : (
                    <a
                      href={downloadHref(document.id)}
                      aria-label={t("download", { name })}
                      className="underline"
                    >
                      {name}
                    </a>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Badge>{statuses(document.status)}</Badge>
                </td>
                <td className="px-3 py-2">
                  {format.dateTime(new Date(document.created_at), { dateStyle: "medium" })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Applications({ candidate, canManage }: { candidate: Candidate; canManage: boolean }) {
  const t = useTranslations("candidates.applications");
  const stages = useTranslations("candidates.stages");
  const format = useFormatter();
  const queryClient = useQueryClient();
  if (candidate.applications.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <caption className="sr-only">{t("caption")}</caption>
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("job")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("stage")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("hiringStatus")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("applied")}
            </th>
          </tr>
        </thead>
        <tbody>
          {candidate.applications.map((application) => (
            <tr key={application.id} className="border-border border-t">
              <td className="px-3 py-2">
                <Link href={`/jobs/${application.job_id}`} className="hover:underline">
                  {`${application.job_reference} · ${application.job_title}`}
                </Link>
              </td>
              <td className="px-3 py-2">
                <Badge>{stages(application.stage)}</Badge>
              </td>
              <td className="px-3 py-2">
                <ApplicationStatusAction
                  applicationId={application.id}
                  status={application.hiring_status}
                  canManage={canManage}
                  onChanged={() => {
                    void queryClient.invalidateQueries({ queryKey: keys.candidates });
                  }}
                />
              </td>
              <td className="px-3 py-2">
                {format.dateTime(new Date(application.created_at), { dateStyle: "medium" })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
