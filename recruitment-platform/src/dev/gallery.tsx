"use client";

import {
  Avatar,
  Badge,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Checkbox,
  CommandPalette,
  DataTable,
  type DataTableColumn,
  type DataTableLabels,
  Dialog,
  DialogClose,
  DialogContent,
  DialogTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Form,
  FormField,
  IconButton,
  Input,
  KpiTile,
  Label,
  localViewStore,
  Popover,
  PopoverContent,
  PopoverTrigger,
  RadioGroup,
  RadioItem,
  Select,
  SeverityBadge,
  Sheet,
  SheetContent,
  SheetTrigger,
  Skeleton,
  type SortingState,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  Tooltip,
  toast,
  useTheme,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { Bell, Inbox, Plus } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

// A development-only page (404 unless HV_WEB_DEV_TOOLS), so its demo text isn't translated.
const T = {
  title: "Component gallery",
  intro:
    "Every design-system component. Static pieces show in both themes side by side; switch the page theme to check the overlays.",
  themes: { light: "Light", dark: "Dark", system: "System" },
  pageTheme: "Page theme",
  buttons: "Buttons",
  primary: "Primary",
  secondary: "Secondary",
  ghost: "Ghost",
  danger: "Delete",
  disabled: "Disabled",
  small: "Small",
  add: "Add item",
  badges: "Badges",
  tones: ["neutral", "accent", "success", "warning", "danger", "info"] as const,
  severity: { INFO: "Info", WARNING: "Warning", CRITICAL: "Critical" },
  display: "Cards, avatars and placeholders",
  cardTitle: "Backend engineer",
  cardBody: "Bengaluru · Hybrid · 12 candidates",
  person: "Asha Rao",
  kpiLabel: "Open jobs",
  noData: "no data yet",
  emptyTitle: "No candidates yet",
  emptyBody: "Upload resumes to start screening.",
  controls: "Controls",
  inputLabel: "Search candidates",
  textareaLabel: "Recruiter notes",
  checkbox: "Email me a summary",
  switchLabel: "Strict proctoring",
  selectLabel: "Work model",
  selectPlaceholder: "Choose a work model",
  workModels: [
    { value: "onsite", label: "On-site" },
    { value: "hybrid", label: "Hybrid" },
    { value: "remote", label: "Remote" },
  ],
  radioLabel: "Difficulty",
  difficulties: ["Easy", "Medium", "Hard"] as const,
  navigation: "Navigation",
  breadcrumbLabel: "Breadcrumb",
  crumbs: [
    { label: "Jobs", href: "#jobs" },
    { label: "Backend engineer", href: "#job" },
  ],
  tabsLabel: "Interview views",
  tabs: { upcoming: "Upcoming", live: "Live", completed: "Completed" },
  tabBody: {
    upcoming: "Interviews that haven't started.",
    live: "Interviews in progress.",
    completed: "Finished interviews.",
  },
  overlays: "Overlays",
  openDialog: "Open dialog",
  dialogTitle: "Archive this job?",
  dialogBody: "Candidates keep their reports. You can restore the job later.",
  cancel: "Cancel",
  archive: "Archive",
  close: "Close",
  openSheet: "Open sheet",
  sheetTitle: "Notifications",
  menu: "Open menu",
  menuLabel: "Job actions",
  menuItems: ["Edit", "Duplicate", "Archive"],
  popover: "Open popover",
  popoverBody: "Popovers hold short, related controls.",
  tooltip: "Hover or focus me",
  tooltipBody: "Tooltips repeat what's elsewhere; they never hold the only copy.",
  notify: "Show a toast",
  toastTitle: "Job saved",
  palette: "Open command palette",
  paletteLabel: "Go to",
  palettePlaceholder: "Search pages…",
  paletteEmpty: "No matching pages.",
  paletteGroup: "Pages",
  form: "Form",
  email: "Work email",
  emailHint: "We send the interview invitation here.",
  emailError: "Enter a valid email address.",
  submit: "Save",
  saved: "Saved",
  table: "Data table",
  tableCaption: "Demo jobs",
  columns: { title: "Title", location: "Location", status: "Status" },
};

const LABELS: DataTableLabels<DemoJob> = {
  selectAll: "Select all rows",
  selectRow: (row) => `Select ${row.title}`,
  selected: (count) => `${count} selected`,
  clearSelection: "Clear selection",
  columns: "Columns",
  views: "Saved views",
  viewName: "View name",
  saveView: "Save view",
  applyView: (name) => `Apply view ${name}`,
  deleteView: (name) => `Delete view ${name}`,
  noViews: "No saved views yet.",
};

interface DemoJob {
  id: string;
  title: string;
  location: string;
  status: string;
}

const JOBS: DemoJob[] = [
  { id: "j1", title: "Backend engineer", location: "Bengaluru", status: "Open" },
  { id: "j2", title: "Data analyst", location: "Pune", status: "Paused" },
  { id: "j3", title: "Frontend engineer", location: "Hyderabad", status: "Open" },
  { id: "j4", title: "Engineering manager", location: "Remote", status: "Draft" },
];

const COLUMNS: DataTableColumn<DemoJob>[] = [
  {
    id: "title",
    header: T.columns.title,
    cell: (job) => job.title,
    sortable: true,
    hideable: false,
  },
  { id: "location", header: T.columns.location, cell: (job) => job.location, sortable: true },
  { id: "status", header: T.columns.status, cell: (job) => job.status },
];

const emailSchema = z.object({ email: z.email(T.emailError) });

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-semibold text-lg">{title}</h2>
      {children}
    </section>
  );
}

/** The same content in a light and a dark panel. Content must not carry ids (it renders twice). */
function BothThemes({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {(["light", "dark"] as const).map((theme) => (
        <div
          key={theme}
          data-theme={theme}
          className="rounded-lg border border-border bg-background p-4 text-foreground"
        >
          <p className="mb-3 font-medium text-muted-foreground text-xs">{T.themes[theme]}</p>
          <div className="flex flex-wrap items-center gap-3">{children}</div>
        </div>
      ))}
    </div>
  );
}

function DemoTable() {
  const [sorting, setSorting] = useState<SortingState>([]);
  const store = useMemo(() => localViewStore(), []);
  const rows = useMemo(() => {
    const [sort] = sorting;
    if (!sort) return JOBS;
    const key = sort.id as keyof DemoJob;
    const sorted = [...JOBS].sort((a, b) => a[key].localeCompare(b[key]));
    return sort.desc ? sorted.reverse() : sorted;
  }, [sorting]);
  return (
    <DataTable
      tableId="gallery"
      caption={T.tableCaption}
      columns={COLUMNS}
      rows={rows}
      getRowId={(job) => job.id}
      labels={LABELS}
      sorting={sorting}
      onSortingChange={setSorting}
      viewStore={store}
      bulkActions={() => (
        <Button size="sm" variant="secondary">
          {T.archive}
        </Button>
      )}
    />
  );
}

function DemoForm() {
  const form = useForm<z.infer<typeof emailSchema>>({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: "" },
  });
  return (
    <Form form={form} onSubmit={() => toast(T.saved)} className="flex max-w-sm flex-col gap-3">
      <FormField
        control={form.control}
        name="email"
        label={T.email}
        description={T.emailHint}
        render={(field) => <Input type="email" {...field} />}
      />
      <div>
        <Button type="submit">{T.submit}</Button>
      </div>
    </Form>
  );
}

export function Gallery() {
  const { preference, setPreference } = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);

  return (
    <main id="main" className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semibold text-2xl tracking-tight">{T.title}</h1>
          <p className="mt-1 max-w-2xl text-muted-foreground">{T.intro}</p>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="gallery-theme">{T.pageTheme}</Label>
          <Select
            id="gallery-theme"
            options={(["light", "dark", "system"] as const).map((value) => ({
              value,
              label: T.themes[value],
            }))}
            value={preference}
            onValueChange={(value) => {
              if (value === "light" || value === "dark" || value === "system") setPreference(value);
            }}
          />
        </div>
      </header>

      <Section title={T.buttons}>
        <BothThemes>
          <Button>{T.primary}</Button>
          <Button variant="secondary">{T.secondary}</Button>
          <Button variant="ghost">{T.ghost}</Button>
          <Button variant="danger">{T.danger}</Button>
          <Button disabled>{T.disabled}</Button>
          <Button size="sm">{T.small}</Button>
          <IconButton label={T.add} icon={<Plus aria-hidden />} variant="secondary" />
        </BothThemes>
      </Section>

      <Section title={T.badges}>
        <BothThemes>
          {T.tones.map((tone) => (
            <Badge key={tone} tone={tone}>
              {tone}
            </Badge>
          ))}
          {(["INFO", "WARNING", "CRITICAL"] as const).map((severity) => (
            <SeverityBadge key={severity} severity={severity} label={T.severity[severity]} />
          ))}
        </BothThemes>
      </Section>

      <Section title={T.display}>
        <BothThemes>
          <Card className="w-64">
            <CardHeader>
              <CardTitle>{T.cardTitle}</CardTitle>
            </CardHeader>
            <CardContent className="text-muted-foreground text-sm">{T.cardBody}</CardContent>
          </Card>
          <Avatar name={T.person} />
          <Skeleton className="h-4 w-32" />
          <KpiTile label={T.kpiLabel} value="42" noDataLabel={T.noData} className="w-40" />
          <KpiTile label={T.kpiLabel} value={null} noDataLabel={T.noData} className="w-40" />
          <EmptyState
            icon={<Inbox />}
            title={T.emptyTitle}
            description={T.emptyBody}
            level={3}
            className="w-full"
          />
        </BothThemes>
      </Section>

      <Section title={T.controls}>
        <BothThemes>
          <Input aria-label={T.inputLabel} placeholder={T.inputLabel} className="w-56" />
          <Textarea aria-label={T.textareaLabel} placeholder={T.textareaLabel} className="w-56" />
          <Checkbox aria-label={T.checkbox} defaultChecked />
          <Switch aria-label={T.switchLabel} defaultChecked />
        </BothThemes>
        <div className="flex flex-wrap gap-6">
          <div className="flex w-56 flex-col gap-1">
            <Label htmlFor="gallery-work-model">{T.selectLabel}</Label>
            <Select
              id="gallery-work-model"
              options={T.workModels}
              placeholder={T.selectPlaceholder}
            />
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 font-medium text-sm">{T.radioLabel}</legend>
            <RadioGroup defaultValue="Medium">
              {T.difficulties.map((difficulty) => (
                <div key={difficulty} className="flex items-center gap-2">
                  <RadioItem id={`gallery-${difficulty}`} value={difficulty} />
                  <Label htmlFor={`gallery-${difficulty}`}>{difficulty}</Label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>
        </div>
      </Section>

      <Section title={T.navigation}>
        <Breadcrumbs label={T.breadcrumbLabel} items={T.crumbs} />
        <Tabs defaultValue="upcoming">
          <TabsList label={T.tabsLabel}>
            {(["upcoming", "live", "completed"] as const).map((tab) => (
              <TabsTrigger key={tab} value={tab}>
                {T.tabs[tab]}
              </TabsTrigger>
            ))}
          </TabsList>
          {(["upcoming", "live", "completed"] as const).map((tab) => (
            <TabsContent key={tab} value={tab} className="text-sm">
              {T.tabBody[tab]}
            </TabsContent>
          ))}
        </Tabs>
      </Section>

      <Section title={T.overlays}>
        <div className="flex flex-wrap gap-3">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary">{T.openDialog}</Button>
            </DialogTrigger>
            <DialogContent
              title={T.dialogTitle}
              description={T.dialogBody}
              closeLabel={T.close}
              footer={
                <>
                  <DialogClose asChild>
                    <Button variant="ghost">{T.cancel}</Button>
                  </DialogClose>
                  <DialogClose asChild>
                    <Button variant="danger">{T.archive}</Button>
                  </DialogClose>
                </>
              }
            />
          </Dialog>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="secondary">{T.openSheet}</Button>
            </SheetTrigger>
            <SheetContent title={T.sheetTitle} closeLabel={T.close}>
              <EmptyState icon={<Bell />} title={T.emptyTitle} level={3} />
            </SheetContent>
          </Sheet>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary">{T.menu}</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>{T.menuLabel}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {T.menuItems.map((item) => (
                <DropdownMenuItem key={item}>{item}</DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="secondary">{T.popover}</Button>
            </PopoverTrigger>
            <PopoverContent className="text-sm">{T.popoverBody}</PopoverContent>
          </Popover>
          <Tooltip content={T.tooltipBody}>
            <Button variant="secondary">{T.tooltip}</Button>
          </Tooltip>
          <Button variant="secondary" onClick={() => toast(T.toastTitle)}>
            {T.notify}
          </Button>
          <Button variant="secondary" onClick={() => setPaletteOpen(true)}>
            {T.palette}
          </Button>
          <CommandPalette
            open={paletteOpen}
            onOpenChange={setPaletteOpen}
            label={T.paletteLabel}
            placeholder={T.palettePlaceholder}
            emptyLabel={T.paletteEmpty}
            groups={[
              {
                heading: T.paletteGroup,
                items: JOBS.map((job) => ({
                  id: job.id,
                  label: job.title,
                  onSelect: () => toast(job.title),
                })),
              },
            ]}
          />
        </div>
      </Section>

      <Section title={T.form}>
        <DemoForm />
      </Section>

      <Section title={T.table}>
        <DemoTable />
      </Section>
    </main>
  );
}
