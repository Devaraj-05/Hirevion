import { Button, Checkbox, Dialog, DialogContent, Label, Skeleton, Textarea } from "@hirevion/ui";
import { useEffect, useId, useState } from "react";
import { useTranslations } from "use-intl";
import {
  ACCOMMODATION_KINDS,
  type AccommodationKind,
  type Briefing,
  commands,
} from "../native/commands";
import { agreeToTerms } from "./consent";
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

/** Consent (PRD §30, §83) as one Terms and Conditions checkbox (product-owner decision,
 * 2026-11-15): the terms list every item collected, and agreeing accepts them all. A candidate
 * who can't agree can still ask for an accommodation or another way to be assessed. */
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
  const [agreed, setAgreed] = useState(false);
  const [terms, setTerms] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [asking, setAsking] = useState(false);
  const [kinds, setKinds] = useState<AccommodationKind[]>([]);
  const [note, setNote] = useState("");
  const [requested, setRequested] = useState(false);

  const items = briefing.notice.items;

  async function submit() {
    setWorking(true);
    setError(null);
    try {
      const result = await commands.consents(interviewId, agreeToTerms(briefing.notice));
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
      <div className="flex items-start gap-3 rounded-md border border-border p-4">
        <Checkbox
          id={`${id}-terms`}
          checked={agreed}
          onCheckedChange={(checked) => setAgreed(checked === true)}
        />
        <div className="grid gap-1">
          <Label htmlFor={`${id}-terms`} className="font-medium">
            {t("agreeTerms")}
          </Label>
          <Button
            variant="ghost"
            className="h-auto w-fit p-0 text-accent underline hover:bg-transparent"
            onClick={() => setTerms(true)}
          >
            {t("readTerms")}
          </Button>
        </div>
      </div>
      <Dialog open={terms} onOpenChange={setTerms}>
        <DialogContent
          title={t("termsTitle")}
          description={t("termsIntro")}
          closeLabel={t("close")}
          className="max-h-[85vh] overflow-y-auto"
        >
          <ul className="grid gap-3">
            {items.map((item) => (
              <li key={item.purpose} className="grid gap-1">
                <span className="font-medium">
                  {t(`purposes.${item.purpose}` as "purposes.camera")}
                  {item.required ? ` (${t("required")})` : ""}
                </span>
                <span className="text-muted-foreground text-sm">{item.text}</span>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={working || !agreed} onClick={() => void submit()}>
          {t("agree")}
        </Button>
        <Button variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
        <Button
          variant="ghost"
          className="text-muted-foreground"
          aria-expanded={asking}
          onClick={() => setAsking((open) => !open)}
        >
          {t("cantAgree")}
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
