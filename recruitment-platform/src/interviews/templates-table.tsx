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
import { LayoutTemplate, Plus } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { Pager } from "@/data/pager";
import { QueryFailed } from "@/data/query-failed";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";
import { listTemplates, type TemplateSummary } from "./api";
import { keys } from "./template-form";

const FILTERS = ["status", "q"] as const;
const PAGE_SIZE = 25;
const templateName = (template: TemplateSummary) => template.name;

/** The interview templates (PRD §21), most recently changed first; archived ones on request. */
export function TemplatesTable({ canManage }: { canManage: boolean }) {
  const t = useTranslations("interviews.templates");
  const settings = useTranslations("interviews.settings");
  const format = useFormatter();
  const labels = useTableLabels(templateName);
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");
  const status = filters.status === "archived" ? "archived" : "active";
  const query = { status, q: filters.q || undefined } as const;
  const page = useCursorPage([...keys.list, query], (cursor) =>
    listTemplates({ ...query, cursor, limit: PAGE_SIZE }),
  );
  const filtered = Boolean(query.q) || status === "archived";

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const columns = useMemo<DataTableColumn<TemplateSummary>[]>(
    () => [
      {
        id: "name",
        header: t("name"),
        hideable: false,
        cell: (template) => (
          <Link
            href={`/interviews/templates/${template.id}`}
            className="grid hover:underline focus-visible:underline"
          >
            <span className="font-medium">{template.name}</span>
            {template.description ? (
              <span className="line-clamp-1 text-muted-foreground text-xs">
                {template.description}
              </span>
            ) : null}
          </Link>
        ),
      },
      {
        id: "length",
        header: t("length"),
        cell: (template) =>
          t("lengthValue", { minutes: template.duration_minutes, count: template.question_count }),
      },
      {
        id: "proctoring",
        header: settings("proctoring"),
        cell: (template) => settings(`levels.${template.proctoring_level}`),
      },
      {
        id: "thirdEye",
        header: settings("thirdEye"),
        cell: (template) => settings(`thirdEyeModes.${template.third_eye}`),
      },
      {
        id: "coding",
        header: settings("coding"),
        cell: (template) => (template.coding ? <Badge tone="info">{t("withCoding")}</Badge> : "—"),
      },
      { id: "version", header: t("versionColumn"), cell: (template) => template.version },
      {
        id: "updated",
        header: t("updated"),
        cell: (template) => format.dateTime(new Date(template.updated_at), { dateStyle: "medium" }),
      },
    ],
    [t, settings, format],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <form onSubmit={submitSearch} className="min-w-56 flex-1">
          <Input
            type="search"
            aria-label={t("search")}
            placeholder={t("search")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </form>
        <NativeSelect
          aria-label={t("statusFilter")}
          className="w-40"
          value={status}
          onChange={(event) =>
            setFilters({ ...filters, status: event.target.value === "archived" ? "archived" : "" })
          }
          options={[
            { value: "active", label: t("statuses.active") },
            { value: "archived", label: t("statuses.archived") },
          ]}
        />
        {canManage ? (
          <Button asChild>
            <Link href="/interviews/templates/new">
              <Plus className="size-4" aria-hidden />
              {t("new")}
            </Link>
          </Button>
        ) : null}
      </div>
      <DataTable
        tableId="interview-templates"
        caption={t("caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(template) => template.id}
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
              icon={<LayoutTemplate />}
              title={filtered ? t("noMatchTitle") : t("emptyTitle")}
              description={filtered ? t("noMatchHint") : t("emptyHint")}
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
    </div>
  );
}
