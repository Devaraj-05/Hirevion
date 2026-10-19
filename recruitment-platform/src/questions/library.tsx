"use client";

import {
  Badge,
  Button,
  DataTable,
  type DataTableColumn,
  EmptyState,
  Input,
  localViewStore,
  NativeSelect,
} from "@hirevion/ui";
import { BookOpen, Plus, Sparkles } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { Pager } from "@/data/pager";
import { QueryFailed } from "@/data/query-failed";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";
import {
  type Category,
  DIFFICULTIES,
  type Difficulty,
  listQuestions,
  QUESTION_TYPES,
  type Question,
  type QuestionStatus,
  type QuestionType,
} from "./api";
import { GenerateDialog } from "./generate-dialog";
import { keys, QuestionEditor, STATUS_TONES } from "./question-editor";

const FILTERS = ["category", "status", "type", "difficulty", "q"] as const;
const ANY = "";
const PAGE_SIZE = 25;
const STATUSES = ["approved", "draft", "archived"] as const satisfies readonly QuestionStatus[];
const questionText = (question: Question) => question.text;

/** The question library (PRD §7, §22): the category tab, status, type, difficulty and search
 * live in the URL. Drafts, including the AI's, wait for approval before anything can use them. */
export function QuestionLibrary({
  canManage,
  canViewJobs = true,
  canViewCandidates = true,
  canViewTemplates = true,
}: {
  canManage: boolean;
  /** What the reader may read, so the AI-draft dialog offers only choices it can load. */
  canViewJobs?: boolean;
  canViewCandidates?: boolean;
  canViewTemplates?: boolean;
}) {
  const t = useTranslations("questions");
  const format = useFormatter();
  const labels = useTableLabels(questionText);
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");
  const [open, setOpen] = useState<string | null | undefined>(undefined);
  const [generating, setGenerating] = useState(false);

  const query = {
    category: (filters.category || undefined) as Category | undefined,
    status: (filters.status || undefined) as QuestionStatus | undefined,
    type: (filters.type || undefined) as QuestionType | undefined,
    difficulty: (filters.difficulty || undefined) as Difficulty | undefined,
    q: filters.q || undefined,
  };
  const page = useCursorPage([...keys.list, query], (cursor) =>
    listQuestions({ ...query, cursor, limit: PAGE_SIZE }),
  );
  const filtered = Boolean(query.status || query.type || query.difficulty || query.q);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const columns = useMemo<DataTableColumn<Question>[]>(
    () => [
      {
        id: "text",
        header: t("table.question"),
        hideable: false,
        cell: (question) => (
          <button
            type="button"
            onClick={() => setOpen(question.id)}
            aria-label={t("table.open", { text: question.text.slice(0, 60) })}
            className="grid max-w-xl text-left hover:underline focus-visible:underline"
          >
            <span className="line-clamp-2">{question.text}</span>
            {question.topic ? (
              <span className="text-muted-foreground text-xs">{question.topic}</span>
            ) : null}
          </button>
        ),
      },
      { id: "skill", header: t("fields.skill"), cell: (question) => question.skill_name },
      { id: "type", header: t("fields.type"), cell: (question) => t(`types.${question.type}`) },
      {
        id: "difficulty",
        header: t("fields.difficulty"),
        cell: (question) => t(`difficulties.${question.difficulty}`),
      },
      {
        id: "status",
        header: t("table.status"),
        cell: (question) => (
          <span className="flex flex-wrap gap-1">
            <Badge tone={STATUS_TONES[question.status]}>{t(`statuses.${question.status}`)}</Badge>
            {question.source === "ai" ? <Badge tone="info">{t("aiDraft")}</Badge> : null}
          </span>
        ),
      },
      {
        id: "updated",
        header: t("table.updated"),
        cell: (question) => format.dateTime(new Date(question.updated_at), { dateStyle: "medium" }),
      },
    ],
    [t, format],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <form onSubmit={submitSearch} className="min-w-56 flex-1">
          <Input
            type="search"
            aria-label={t("table.search")}
            placeholder={t("table.search")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </form>
        <NativeSelect
          aria-label={t("table.status")}
          className="w-40"
          value={filters.status ?? ANY}
          onChange={(event) => setFilters({ ...filters, status: event.target.value })}
          options={[
            { value: ANY, label: t("table.anyStatus") },
            ...STATUSES.map((status) => ({ value: status, label: t(`statuses.${status}`) })),
          ]}
        />
        <NativeSelect
          aria-label={t("fields.type")}
          className="w-44"
          value={filters.type ?? ANY}
          onChange={(event) => setFilters({ ...filters, type: event.target.value })}
          options={[
            { value: ANY, label: t("table.anyType") },
            ...QUESTION_TYPES.map((type) => ({ value: type, label: t(`types.${type}`) })),
          ]}
        />
        <NativeSelect
          aria-label={t("fields.difficulty")}
          className="w-36"
          value={filters.difficulty ?? ANY}
          onChange={(event) => setFilters({ ...filters, difficulty: event.target.value })}
          options={[
            { value: ANY, label: t("table.anyDifficulty") },
            ...DIFFICULTIES.map((level) => ({ value: level, label: t(`difficulties.${level}`) })),
          ]}
        />
        {canManage ? (
          <>
            <Button variant="secondary" onClick={() => setGenerating(true)}>
              <Sparkles className="size-4" aria-hidden />
              {t("table.generate")}
            </Button>
            <Button onClick={() => setOpen(null)}>
              <Plus className="size-4" aria-hidden />
              {t("table.new")}
            </Button>
          </>
        ) : null}
      </div>
      <DataTable
        tableId="questions"
        caption={t("table.caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(question) => question.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : page.error ? (
            <QueryFailed onRetry={page.refetch} />
          ) : (
            <EmptyState
              icon={<BookOpen />}
              title={filtered ? t("table.noMatchTitle") : t("table.emptyTitle")}
              description={filtered ? t("table.noMatchHint") : t("table.emptyHint")}
            />
          )
        }
        footer={
          <Pager
            hasPrevious={page.hasPrevious}
            hasNext={page.hasNext}
            onPrevious={page.previousPage}
            onNext={page.nextPage}
          />
        }
      />
      {open !== undefined ? (
        <QuestionEditor
          questionId={open}
          canManage={canManage}
          onClose={() => setOpen(undefined)}
        />
      ) : null}
      {generating ? (
        <GenerateDialog
          onClose={() => setGenerating(false)}
          canViewJobs={canViewJobs}
          canViewCandidates={canViewCandidates}
          canViewTemplates={canViewTemplates}
          onGenerated={() => {
            // The new drafts show whatever filter was set before.
            setGenerating(false);
            setSearch("");
            setFilters({ status: "draft" });
          }}
        />
      ) : null}
    </div>
  );
}
