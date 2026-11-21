import { Checkbox, Dialog, DialogContent, Label, Textarea } from "@hirevion/ui";
import { ShieldAlert } from "lucide-react";
import { useId, useState } from "react";
import { useTranslations } from "use-intl";
import {
  ACCOMMODATION_KINDS,
  type AccommodationKind,
  type Briefing,
  commands,
} from "../../native/commands";
import { Notice, PillButton } from "../../ui/kit";
import { agreeToTerms } from "../consent";
import { type ErrorKey, errorKey } from "../errors";

/**
 * Step 3, consent (PRD §30, §83) as one Terms and Conditions checkbox (product owner,
 * 2026-11-15): the terms list every item collected, and ticking the box accepts them all.
 * A candidate who can't agree can ask for an accommodation instead.
 */
export function TermsStep({
  interviewId,
  briefing,
  onAgreed,
  onError,
}: {
  interviewId: string;
  briefing: Briefing;
  onAgreed: (consentId: string) => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("consent");
  const p = useTranslations("prepare.terms");
  const errors = useTranslations("errors");
  const id = useId();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [incomplete, setIncomplete] = useState(false);
  const [reading, setReading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [kinds, setKinds] = useState<AccommodationKind[]>([]);
  const [note, setNote] = useState("");
  const [requested, setRequested] = useState(false);

  async function agree() {
    setWorking(true);
    setError(null);
    setIncomplete(false);
    try {
      const result = await commands.consents(interviewId, agreeToTerms(briefing.notice));
      if (result.complete) onAgreed(result.id);
      else {
        setIncomplete(true);
        setAsking(true);
      }
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
    <div className="grid gap-4">
      {/* A firm warning before the candidate agrees (owner, 2026-11-21). The AI says it again
          when the interview starts. */}
      <div
        role="note"
        aria-labelledby={`${id}-warning`}
        className="flex items-start gap-3 rounded-2xl border border-danger/25 bg-danger-subtle p-4"
      >
        <ShieldAlert className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div className="grid min-w-0 gap-1">
          <p id={`${id}-warning`} className="font-semibold text-danger">
            {p("warningTitle")}
          </p>
          <p className="text-[0.9rem] leading-snug">{p("warning")}</p>
        </div>
      </div>
      <div className="flex items-start gap-3 rounded-2xl bg-surface-muted p-4">
        <Checkbox
          id={`${id}-terms`}
          className="mt-0.5 size-5 rounded-md"
          checked={working}
          disabled={working}
          onCheckedChange={(checked) => {
            if (checked === true) void agree();
          }}
        />
        <div className="grid gap-1">
          <Label htmlFor={`${id}-terms`} className="font-medium text-[0.95rem]">
            {t("agreeTerms")}
          </Label>
          <button
            type="button"
            className="w-fit text-[0.9rem] text-accent hover:underline"
            onClick={() => setReading(true)}
          >
            {t("readTerms")}
          </button>
        </div>
      </div>

      {error ? (
        <Notice role="alert" tone="danger">
          {errors(error)}
        </Notice>
      ) : null}
      {incomplete ? <Notice role="alert">{p("incomplete")}</Notice> : null}

      <button
        type="button"
        className="w-fit text-[0.9rem] text-muted-foreground hover:text-foreground hover:underline"
        aria-expanded={asking}
        onClick={() => setAsking((open) => !open)}
      >
        {t("cantAgree")}
      </button>

      {asking ? (
        <section
          className="fade-in grid gap-3 rounded-2xl border border-border/70 p-4"
          aria-labelledby={`${id}-acc`}
        >
          <h3 id={`${id}-acc`} className="font-semibold">
            {t("accommodationTitle")}
          </h3>
          <p className="text-[0.92rem] text-muted-foreground">{t("accommodationIntro")}</p>
          <ul className="grid gap-2 sm:grid-cols-2">
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
            className="rounded-xl"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          {requested ? (
            <p role="status" className="text-success">
              {t("requested")}
            </p>
          ) : (
            <PillButton
              variant="secondary"
              className="w-fit"
              disabled={kinds.length === 0 && !note.trim()}
              onClick={() => void requestAccommodation()}
            >
              {t("request")}
            </PillButton>
          )}
        </section>
      ) : null}

      <Dialog open={reading} onOpenChange={setReading}>
        <DialogContent
          title={t("termsTitle")}
          description={t("termsIntro")}
          closeLabel={t("close")}
          className="max-h-[80vh] overflow-y-auto rounded-[20px]"
        >
          <ul className="grid gap-4">
            {briefing.notice.items.map((item) => (
              <li key={item.purpose} className="grid gap-1">
                <span className="font-semibold">
                  {t(`purposes.${item.purpose}` as "purposes.camera")}
                  {item.required ? (
                    <span className="font-normal text-muted-foreground"> ({t("required")})</span>
                  ) : null}
                </span>
                <span className="text-[0.92rem] text-muted-foreground leading-relaxed">
                  {item.text}
                </span>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </div>
  );
}
