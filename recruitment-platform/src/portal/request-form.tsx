"use client";

import { Button, Checkbox, Input, Label, NativeSelect, Textarea } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { createPortalRequest, type PortalRequestCreate, type RequestKind } from "./api";

/** The portal's request form (master plan §6.3): what each kind needs mirrors the API's rules. */

export const REQUEST_KINDS = [
  "reschedule",
  "support",
  "accommodation",
  "alternative_process",
  "data_access",
  "data_correction",
  "data_erasure",
  "grievance",
  "nomination",
  "consent_withdrawal",
] as const satisfies readonly RequestKind[];

const ACCOMMODATIONS = [
  "extended_time",
  "text_answers",
  "breaks",
  "assistive_technology",
  "relaxed_gaze",
  "third_eye_waiver",
] as const;
const PURPOSES = [
  "camera",
  "microphone",
  "screen",
  "audio",
  "video",
  "third_eye",
  "transcript",
  "coding_activity",
  "system_telemetry",
  "proctoring_events",
] as const;
const NEEDS_INTERVIEW = new Set<RequestKind>(["reschedule", "accommodation"]);
const NEEDS_MESSAGE = new Set<RequestKind>([
  "reschedule",
  "support",
  "alternative_process",
  "data_correction",
  "grievance",
]);
const MESSAGE_MAX = 4000;

export interface InterviewChoice {
  id: string;
  label: string;
}

function isKind(value: string | null | undefined): value is RequestKind {
  return REQUEST_KINDS.some((kind) => kind === value);
}

type Problems = Partial<Record<"interview" | "message" | "choices" | "nominee", string>>;

export function RequestForm({
  interviews,
  initialKind,
  initialInterview,
  onSent,
}: {
  interviews: readonly InterviewChoice[];
  initialKind?: string | null;
  initialInterview?: string | null;
  onSent: () => void;
}) {
  const t = useTranslations("portal.requests");
  const disclosures = useTranslations("portal.noticesPage.disclosures");
  const id = useId();
  const [kind, setKind] = useState<RequestKind>(isKind(initialKind) ? initialKind : "support");
  const [interview, setInterview] = useState(
    interviews.some((item) => item.id === initialInterview) ? (initialInterview ?? "") : "",
  );
  const [message, setMessage] = useState("");
  const [text, setText] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Set<string>>(new Set());
  const [problems, setProblems] = useState<Problems>({});
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const [sending, setSending] = useState(false);

  const field = (name: string) => text[name]?.trim() ?? "";
  const setField = (name: string, value: string) =>
    setText((current) => ({ ...current, [name]: value }));
  const toggle = (value: string) =>
    setChoices((current) => {
      const next = new Set(current);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  const changeKind = (value: string) => {
    if (!isKind(value)) return;
    setKind(value);
    setChoices(new Set());
    setProblems({});
  };

  function build(): PortalRequestCreate | null {
    const found: Problems = {};
    if (NEEDS_INTERVIEW.has(kind) && !interview) found.interview = t("interviewRequired");
    if (NEEDS_MESSAGE.has(kind) && !message.trim()) found.message = t("messageRequired");
    if ((kind === "accommodation" || kind === "consent_withdrawal") && choices.size === 0) {
      found.choices = t("choiceRequired");
    }
    if (
      kind === "nomination" &&
      (!field("nominee_name") || !field("nominee_email").includes("@"))
    ) {
      found.nominee = t("nomineeRequired");
    }
    setProblems(found);
    if (Object.keys(found).length > 0) return null;
    const details: Record<string, unknown> = {};
    const keep = (name: string) => {
      if (field(name)) details[name] = field(name);
    };
    if (kind === "reschedule") keep("preferred");
    if (kind === "data_correction") keep("field");
    if (kind === "nomination") {
      keep("nominee_name");
      keep("nominee_email");
      keep("relationship");
    }
    if (kind === "accommodation") details.kinds = ACCOMMODATIONS.filter((k) => choices.has(k));
    if (kind === "consent_withdrawal") details.purposes = PURPOSES.filter((p) => choices.has(p));
    return {
      kind,
      ...(NEEDS_INTERVIEW.has(kind) ? { interview_id: interview } : {}),
      message: message.trim(),
      details,
    };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setOutcome(null);
    const body = build();
    if (!body) return;
    setSending(true);
    const result = await createPortalRequest(body);
    setSending(false);
    if (result.ok) {
      setOutcome({ ok: true, text: t("sent") });
      setMessage("");
      setText({});
      setChoices(new Set());
      onSent();
    } else if (result.reason === "invalid") {
      setOutcome({ ok: false, text: t("failed", { problem: result.problem }) });
    } else {
      setOutcome({
        ok: false,
        text: result.reason === "limited" ? t("limited") : t("unavailable"),
      });
    }
  }

  const error = (name: keyof Problems) =>
    problems[name] ? (
      <p id={`${id}-${name}-error`} className="text-danger text-sm">
        {problems[name]}
      </p>
    ) : null;
  const described = (name: keyof Problems) =>
    problems[name] ? { "aria-invalid": true, "aria-describedby": `${id}-${name}-error` } : {};
  const textInput = (name: string, label: string, type = "text") => (
    <div className="grid gap-1">
      <Label htmlFor={`${id}-${name}`}>{label}</Label>
      <Input
        id={`${id}-${name}`}
        type={type}
        maxLength={500}
        value={text[name] ?? ""}
        onChange={(event) => setField(name, event.target.value)}
        {...(name.startsWith("nominee") ? described("nominee") : {})}
      />
    </div>
  );
  const checkboxes = (
    legend: string,
    values: readonly string[],
    label: (value: string) => string,
  ) => (
    <fieldset className="grid gap-2" {...described("choices")}>
      <legend className="mb-1 font-medium text-sm">{legend}</legend>
      {values.map((value) => (
        <div key={value} className="flex items-start gap-2">
          <Checkbox
            id={`${id}-${value}`}
            checked={choices.has(value)}
            onCheckedChange={() => toggle(value)}
            className="mt-0.5"
          />
          <Label htmlFor={`${id}-${value}`} className="font-normal">
            {label(value)}
          </Label>
        </div>
      ))}
      {error("choices")}
    </fieldset>
  );

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      {outcome ? (
        <p
          role={outcome.ok ? "status" : "alert"}
          className={
            outcome.ok
              ? "rounded-md bg-success-subtle px-3 py-2 text-sm"
              : "rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
          }
        >
          {outcome.text}
        </p>
      ) : null}
      <div className="grid gap-1">
        <Label htmlFor={`${id}-kind`}>{t("kind")}</Label>
        <NativeSelect
          id={`${id}-kind`}
          value={kind}
          onChange={(event) => changeKind(event.target.value)}
          options={REQUEST_KINDS.map((value) => ({ value, label: t(`kinds.${value}`) }))}
        />
      </div>
      {NEEDS_INTERVIEW.has(kind) ? (
        <div className="grid gap-1">
          <Label htmlFor={`${id}-interview`}>{t("interview")}</Label>
          <NativeSelect
            id={`${id}-interview`}
            value={interview}
            onChange={(event) => setInterview(event.target.value)}
            options={[
              { value: "", label: interviews.length ? t("chooseInterview") : t("noInterviews") },
              ...interviews.map((item) => ({ value: item.id, label: item.label })),
            ]}
            {...described("interview")}
          />
          {error("interview")}
        </div>
      ) : null}
      {kind === "reschedule" ? textInput("preferred", t("preferred")) : null}
      {kind === "data_correction" ? textInput("field", t("field")) : null}
      {kind === "nomination" ? (
        <>
          {textInput("nominee_name", t("nomineeName"))}
          {textInput("nominee_email", t("nomineeEmail"), "email")}
          {textInput("relationship", t("relationship"))}
          {error("nominee")}
        </>
      ) : null}
      {kind === "accommodation"
        ? checkboxes(t("adjustments"), ACCOMMODATIONS, (value) =>
            t(`accommodationKinds.${value as (typeof ACCOMMODATIONS)[number]}`),
          )
        : null}
      {kind === "consent_withdrawal"
        ? checkboxes(t("purposes"), PURPOSES, (value) =>
            disclosures(value as (typeof PURPOSES)[number]),
          )
        : null}
      <div className="grid gap-1">
        <Label htmlFor={`${id}-message`}>{t("message")}</Label>
        <Textarea
          id={`${id}-message`}
          value={message}
          maxLength={MESSAGE_MAX}
          onChange={(event) => setMessage(event.target.value)}
          {...described("message")}
        />
        {error("message")}
      </div>
      <div>
        <Button type="submit" disabled={sending}>
          {t("submit")}
        </Button>
      </div>
    </form>
  );
}
