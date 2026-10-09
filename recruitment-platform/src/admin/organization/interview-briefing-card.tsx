"use client";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  getInterviewBriefing,
  type InterviewBriefing,
  saveInterviewBriefing,
  sessionKeys,
} from "@/interviews/session-api";

const FAQ_MAX = 50;

interface Draft {
  instructions: string;
  faq: { key: number; question: string; answer: string }[];
}

function toDraft(saved: InterviewBriefing): Draft {
  return {
    instructions: (saved.instructions ?? []).join("\n"),
    faq: (saved.faq ?? []).map((item, key) => ({ key, ...item })),
  };
}

/** What candidates are told before an interview (PRD §30), and the FAQ the AI interviewer
 * answers their final questions from (§35): it never answers from anything else. */
export function InterviewBriefingCard() {
  const t = useTranslations("admin.organization.interviewBriefing");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const briefing = useQuery({ queryKey: sessionKeys.briefing, queryFn: getInterviewBriefing });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [nextKey, setNextKey] = useState(1000);
  useEffect(() => {
    if (briefing.data && draft === null) setDraft(toDraft(briefing.data));
  }, [briefing.data, draft]);
  const save = useMutation({
    mutationFn: (body: InterviewBriefing) => saveInterviewBriefing(body),
    onSuccess: (saved) => {
      queryClient.setQueryData(sessionKeys.briefing, saved);
      setDraft(toDraft(saved));
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft === null) return;
    save.mutate({
      instructions: draft.instructions
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      faq: draft.faq
        .map(({ question, answer }) => ({ question: question.trim(), answer: answer.trim() }))
        .filter((item) => item.question || item.answer),
    });
  }

  function update(key: number, field: "question" | "answer", value: string) {
    setDraft((current) =>
      current === null
        ? current
        : {
            ...current,
            faq: current.faq.map((item) => (item.key === key ? { ...item, [field]: value } : item)),
          },
    );
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {draft === null ? (
          briefing.isError ? (
            <div className="grid justify-items-start gap-2">
              <p className="text-sm" role="alert">
                {t("loadFailed")}
              </p>
              <Button size="sm" variant="secondary" onClick={() => void briefing.refetch()}>
                {t("retry")}
              </Button>
            </div>
          ) : (
            <Skeleton className="h-24 w-full" />
          )
        ) : (
          <form className="grid gap-4" onSubmit={submit}>
            <div className="grid gap-1">
              <Label htmlFor={`${id}-instructions`}>{t("instructions")}</Label>
              <Textarea
                id={`${id}-instructions`}
                rows={5}
                value={draft.instructions}
                aria-describedby={`${id}-instructions-hint`}
                onChange={(event) => setDraft({ ...draft, instructions: event.target.value })}
              />
              <p id={`${id}-instructions-hint`} className="text-muted-foreground text-xs">
                {t("instructionsHint")}
              </p>
            </div>
            <fieldset className="grid gap-3">
              <legend className="mb-1 font-medium text-sm">{t("faq")}</legend>
              <p className="text-muted-foreground text-xs">{t("faqHint")}</p>
              {draft.faq.map((item, index) => (
                <div key={item.key} className="grid gap-2 rounded-md border p-3">
                  <Label htmlFor={`${id}-q-${item.key}`}>
                    {t("question", { number: index + 1 })}
                  </Label>
                  <Input
                    id={`${id}-q-${item.key}`}
                    value={item.question}
                    maxLength={300}
                    onChange={(event) => update(item.key, "question", event.target.value)}
                  />
                  <Label htmlFor={`${id}-a-${item.key}`}>{t("answer")}</Label>
                  <Textarea
                    id={`${id}-a-${item.key}`}
                    value={item.answer}
                    maxLength={2000}
                    onChange={(event) => update(item.key, "answer", event.target.value)}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="justify-self-start"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        faq: draft.faq.filter((other) => other.key !== item.key),
                      })
                    }
                  >
                    <Trash2 className="size-4" aria-hidden />
                    {t("remove", { number: index + 1 })}
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="justify-self-start"
                disabled={draft.faq.length >= FAQ_MAX}
                onClick={() => {
                  setDraft({
                    ...draft,
                    faq: [...draft.faq, { key: nextKey, question: "", answer: "" }],
                  });
                  setNextKey(nextKey + 1);
                }}
              >
                <Plus className="size-4" aria-hidden />
                {t("add")}
              </Button>
            </fieldset>
            <Button type="submit" className="justify-self-start" disabled={save.isPending}>
              {t("save")}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
