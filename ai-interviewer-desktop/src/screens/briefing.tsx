import { Button, Checkbox, Label, Skeleton, Textarea } from "@hirevion/ui";
import { useEffect, useId, useState } from "react";
import { useTranslations } from "use-intl";
import {
  ACCOMMODATION_KINDS,
  type AccommodationKind,
  type Briefing,
  type ConsentPurpose,
  commands,
} from "../native/commands";
import { type ErrorKey, errorKey } from "./errors";
import { ErrorText } from "./shell";

/** PRD §30's instructions, from the server so each organisation can set them. */
export function BriefingScreen({
  interviewId,
  onRead,
  onBack,
  onError,
}: {
  interviewId: string;
  onRead: (briefing: Briefing) => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("briefing");
  const errors = useTranslations("errors");
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [error, setError] = useState<ErrorKey | null>(null);

  useEffect(() => {
    commands
      .briefing(interviewId)
      .then(setBriefing)
      .catch((failure: unknown) => {
        onError(failure);
        setError(errorKey(failure));
      });
  }, [interviewId, onError]);

  return (
    <section className="grid gap-5" aria-labelledby="briefing-title">
      <h1 id="briefing-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      {briefing ? (
        <>
          <ol className="grid list-decimal gap-2 pl-6">
            {briefing.instructions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
          {briefing.answer_mode === "text" ? (
            <p className="text-muted-foreground text-sm">{t("textMode")}</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => onRead(briefing)}>{t("continue")}</Button>
            <Button variant="ghost" onClick={onBack}>
              {t("back")}
            </Button>
          </div>
        </>
      ) : error ? null : (
        <Skeleton className="h-40 w-full" />
      )}
    </section>
  );
}

/** Itemised consent (PRD §30, §83): one choice per purpose; required ones must be accepted,
 * or the candidate can ask for an accommodation or another way to be assessed. */
export function ConsentScreen({
  interviewId,
  briefing,
  onConsented,
  onBack,
  onError,
}: {
  interviewId: string;
  briefing: Briefing;
  onConsented: (consentId: string) => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("consent");
  const errors = useTranslations("errors");
  const id = useId();
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [asking, setAsking] = useState(false);
  const [kinds, setKinds] = useState<AccommodationKind[]>([]);
  const [note, setNote] = useState("");
  const [requested, setRequested] = useState(false);

  const items = briefing.notice.items;
  const declinedRequired = items.some((item) => item.required && !accepted[item.purpose]);

  async function submit() {
    setWorking(true);
    setError(null);
    try {
      const result = await commands.consents(interviewId, {
        notice_version: briefing.notice.version,
        items: items.map((item) => ({
          purpose: item.purpose as ConsentPurpose,
          accepted: Boolean(accepted[item.purpose]),
        })),
      });
      if (result.complete) onConsented(result.id);
      else setAsking(true);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    } finally {
      setWorking(false);
    }
  }

  async function requestAccommodation() {
    try {
      await commands.requestAccommodations(interviewId, kinds, note.trim());
      setRequested(true);
    } catch (failure) {
      onError(failure);
      setError(errorKey(failure));
    }
  }

  return (
    <section className="grid gap-5" aria-labelledby="consent-title">
      <div className="grid gap-1">
        <h1 id="consent-title" className="font-semibold text-2xl">
          {t("title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("intro")}</p>
      </div>
      <ul className="grid gap-3">
        {items.map((item) => (
          <li
            key={item.purpose}
            className="flex items-start gap-3 rounded-md border border-border p-3"
          >
            <Checkbox
              id={`${id}-${item.purpose}`}
              checked={Boolean(accepted[item.purpose])}
              onCheckedChange={(checked) =>
                setAccepted((previous) => ({ ...previous, [item.purpose]: checked === true }))
              }
            />
            <Label htmlFor={`${id}-${item.purpose}`} className="grid gap-1 font-normal">
              <span className="font-medium">
                {t(`purposes.${item.purpose}` as "purposes.camera")}
                {item.required ? ` (${t("required")})` : ""}
              </span>
              <span className="text-muted-foreground text-sm">{item.text}</span>
            </Label>
          </li>
        ))}
      </ul>
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={working} onClick={() => void submit()}>
          {declinedRequired ? t("submitWithout") : t("agree")}
        </Button>
        <Button variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
      {asking ? (
        <section
          className="grid gap-3 rounded-md border border-border p-4"
          aria-labelledby={`${id}-acc`}
        >
          <h2 id={`${id}-acc`} className="font-medium">
            {t("accommodationTitle")}
          </h2>
          <p className="text-sm">{t("accommodationIntro")}</p>
          <ul className="grid gap-2">
            {ACCOMMODATION_KINDS.map((kind) => (
              <li key={kind} className="flex items-center gap-2">
                <Checkbox
                  id={`${id}-kind-${kind}`}
                  checked={kinds.includes(kind)}
                  onCheckedChange={(checked) =>
                    setKinds((previous) =>
                      checked === true ? [...previous, kind] : previous.filter((k) => k !== kind),
                    )
                  }
                />
                <Label htmlFor={`${id}-kind-${kind}`} className="font-normal">
                  {t(`kinds.${kind}`)}
                </Label>
              </li>
            ))}
          </ul>
          <Label htmlFor={`${id}-note`}>{t("note")}</Label>
          <Textarea
            id={`${id}-note`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          {requested ? (
            <p role="status">{t("requested")}</p>
          ) : (
            <Button
              className="w-fit"
              variant="secondary"
              onClick={() => void requestAccommodation()}
            >
              {t("request")}
            </Button>
          )}
        </section>
      ) : null}
    </section>
  );
}
