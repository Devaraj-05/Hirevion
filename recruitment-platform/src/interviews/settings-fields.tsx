"use client";

import { Checkbox, Input, Label, NativeSelect, Switch } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { CheckboxGroup } from "@/admin/fields";
import {
  CODING_LANGUAGES,
  type CodingLanguage,
  DIFFICULTIES,
  type Difficulty,
  QUESTION_TYPES,
  type QuestionType,
} from "@/questions/api";
import {
  type InterviewDefaults,
  PROCTORING_LEVELS,
  type ProctoringLevel,
  RUBRIC_DIMENSIONS,
  type TemplateVersion,
  THIRD_EYE_MODES,
  type ThirdEye,
} from "./api";

type Dimension = (typeof RUBRIC_DIMENSIONS)[number];
const RECORDING = ["screen", "camera", "audio"] as const;
type Track = (typeof RECORDING)[number];

/** The settings a template version and the organisation's defaults share (PRD §21), as the
 * form holds them: numbers stay text until saved. */
export interface Settings {
  duration_minutes: string;
  question_count: string;
  difficulty: Record<Difficulty, string>;
  question_types: QuestionType[];
  use_resume: boolean;
  use_jd: boolean;
  adaptive_follow_ups: boolean;
  coding: { enabled: boolean; languages: CodingLanguage[]; minutes: string };
  proctoring_level: ProctoringLevel;
  third_eye: ThirdEye;
  recording: Record<Track, boolean>;
  rubric: Record<Dimension, string>;
}

export type SettingsSource = Pick<
  TemplateVersion | InterviewDefaults,
  | "duration_minutes"
  | "question_count"
  | "difficulty"
  | "question_types"
  | "use_resume"
  | "use_jd"
  | "adaptive_follow_ups"
  | "coding"
  | "proctoring_level"
  | "third_eye"
  | "recording"
  | "rubric"
>;

export function settingsOf(source: SettingsSource): Settings {
  const coding = source.coding as {
    enabled?: boolean;
    languages?: CodingLanguage[];
    minutes?: number;
  };
  const weights = Object.fromEntries(
    source.rubric.map((item) => [String(item.dimension), String(item.weight ?? 0)]),
  );
  return {
    duration_minutes: String(source.duration_minutes),
    question_count: String(source.question_count),
    difficulty: Object.fromEntries(
      DIFFICULTIES.map((level) => [level, String(source.difficulty[level] ?? 0)]),
    ) as Record<Difficulty, string>,
    question_types: source.question_types as QuestionType[],
    use_resume: source.use_resume,
    use_jd: source.use_jd,
    adaptive_follow_ups: source.adaptive_follow_ups,
    coding: {
      enabled: Boolean(coding.enabled),
      languages: coding.languages ?? ["python"],
      minutes: String(coding.minutes ?? 20),
    },
    proctoring_level: source.proctoring_level,
    third_eye: source.third_eye,
    recording: {
      screen: source.recording.screen ?? true,
      camera: source.recording.camera ?? true,
      audio: source.recording.audio ?? true,
    },
    rubric: Object.fromEntries(
      RUBRIC_DIMENSIONS.map((dimension) => [dimension, weights[dimension] ?? "0"]),
    ) as Record<Dimension, string>,
  };
}

const whole = (text: string) => Number.parseInt(text, 10) || 0;
const total = (values: Record<string, string>) =>
  Object.values(values).reduce((sum, value) => sum + whole(value), 0);
const within = (text: string, low: number, high: number) => {
  const value = Number(text);
  return Number.isInteger(value) && value >= low && value <= high;
};

export type SettingsProblem = "duration" | "count" | "difficulty" | "types" | "coding" | "rubric";

const everyShare = (values: Record<string, string>) =>
  Object.values(values).every((text) => within(text, 0, 100));

/** What's wrong with the settings, by field; each value is a message under
 * `interviews.settings.problems`. */
export function settingsProblems(settings: Settings): Partial<Record<SettingsProblem, string>> {
  const found: Partial<Record<SettingsProblem, string>> = {};
  if (!within(settings.duration_minutes, 15, 180)) found.duration = "duration";
  if (!within(settings.question_count, 1, 50)) found.count = "count";
  if (!everyShare(settings.difficulty)) found.difficulty = "difficultyRange";
  else if (total(settings.difficulty) !== 100) found.difficulty = "difficulty";
  if (settings.question_types.length === 0) found.types = "types";
  if (settings.coding.enabled) {
    if (settings.coding.languages.length === 0 || !within(settings.coding.minutes, 5, 90))
      found.coding = "coding";
    else if (whole(settings.coding.minutes) > whole(settings.duration_minutes))
      found.coding = "codingTime";
  }
  if (!everyShare(settings.rubric)) found.rubric = "rubricRange";
  else if (total(settings.rubric) !== 100) found.rubric = "rubric";
  return found;
}

/** The settings as the API takes them. */
export function settingsBody(settings: Settings) {
  return {
    duration_minutes: whole(settings.duration_minutes),
    question_count: whole(settings.question_count),
    difficulty: {
      easy: whole(settings.difficulty.easy),
      medium: whole(settings.difficulty.medium),
      hard: whole(settings.difficulty.hard),
    },
    question_types: settings.question_types,
    use_resume: settings.use_resume,
    use_jd: settings.use_jd,
    adaptive_follow_ups: settings.adaptive_follow_ups,
    coding: {
      enabled: settings.coding.enabled,
      languages: settings.coding.languages.length ? settings.coding.languages : ["python" as const],
      // Coding that is switched off keeps a time the API accepts, whatever was typed before.
      minutes:
        settings.coding.enabled || within(settings.coding.minutes, 5, 90)
          ? whole(settings.coding.minutes) || 20
          : 20,
    },
    proctoring_level: settings.proctoring_level,
    third_eye: settings.third_eye,
    recording: settings.recording,
    rubric: RUBRIC_DIMENSIONS.map((dimension) => ({
      dimension,
      weight: whole(settings.rubric[dimension]),
    })),
  };
}

/** The template settings' inputs; `presets` names what each proctoring level turns on. */
export function SettingsFields({
  value,
  onChange,
  showProblems,
  presets,
  readOnly = false,
}: {
  value: Settings;
  onChange: (next: Settings) => void;
  showProblems: boolean;
  presets?: Record<string, string[]> | undefined;
  readOnly?: boolean;
}) {
  const t = useTranslations("interviews.settings");
  const questions = useTranslations("questions");
  const id = useId();
  const found = settingsProblems(value);
  const set = <K extends keyof Settings>(field: K, next: Settings[K]) =>
    onChange({ ...value, [field]: next });
  const problem = (field: SettingsProblem) =>
    showProblems && found[field] ? (
      <p id={`${id}-${field}-problem`} role="alert" className="text-danger text-xs">
        {t(`problems.${found[field] as "duration"}`, {
          total: field === "difficulty" ? total(value.difficulty) : total(value.rubric),
        })}
      </p>
    ) : null;
  // Ties a problem's message to what it is about, for a screen reader.
  const about = (field: SettingsProblem) =>
    showProblems && found[field] ? `${id}-${field}-problem` : undefined;
  const preset = presets?.[value.proctoring_level];

  return (
    <fieldset disabled={readOnly} className="grid gap-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-duration`}>{t("duration")}</Label>
          <Input
            id={`${id}-duration`}
            type="number"
            inputMode="numeric"
            min={15}
            max={180}
            value={value.duration_minutes}
            aria-invalid={showProblems && Boolean(found.duration)}
            aria-describedby={about("duration")}
            onChange={(event) => set("duration_minutes", event.target.value)}
          />
          {problem("duration")}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-count`}>{t("questionCount")}</Label>
          <Input
            id={`${id}-count`}
            type="number"
            inputMode="numeric"
            min={1}
            max={50}
            value={value.question_count}
            aria-invalid={showProblems && Boolean(found.count)}
            aria-describedby={about("count")}
            onChange={(event) => set("question_count", event.target.value)}
          />
          {problem("count")}
        </div>
      </div>

      <fieldset
        className="grid gap-2"
        aria-invalid={showProblems && Boolean(found.difficulty)}
        aria-describedby={about("difficulty")}
      >
        <legend className="mb-1 font-medium text-sm">{t("difficulty")}</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          {DIFFICULTIES.map((level) => (
            <div key={level} className="grid gap-1">
              <Label htmlFor={`${id}-difficulty-${level}`}>
                {questions(`difficulties.${level}`)}
              </Label>
              <Input
                id={`${id}-difficulty-${level}`}
                type="number"
                inputMode="numeric"
                min={0}
                max={100}
                value={value.difficulty[level]}
                onChange={(event) =>
                  set("difficulty", { ...value.difficulty, [level]: event.target.value })
                }
              />
            </div>
          ))}
        </div>
        <p className="text-muted-foreground text-sm">
          {t("totalNow", { total: total(value.difficulty) })}
        </p>
        {problem("difficulty")}
      </fieldset>

      <div className="grid gap-1">
        <CheckboxGroup
          legend={t("questionTypes")}
          options={QUESTION_TYPES.map((type) => ({
            value: type,
            label: questions(`types.${type}`),
          }))}
          value={value.question_types}
          onChange={(next) => set("question_types", next as QuestionType[])}
        />
        {problem("types")}
      </div>

      <fieldset className="grid gap-3">
        <legend className="mb-1 font-medium text-sm">{t("context")}</legend>
        {(
          [
            ["use_resume", "useResume"],
            ["use_jd", "useJd"],
            ["adaptive_follow_ups", "adaptive"],
          ] as const
        ).map(([field, label]) => (
          <div key={field} className="flex items-center gap-2">
            <Switch
              id={`${id}-${field}`}
              checked={value[field]}
              onCheckedChange={(checked) => set(field, checked)}
            />
            <Label htmlFor={`${id}-${field}`}>{t(label)}</Label>
          </div>
        ))}
      </fieldset>

      <fieldset className="grid gap-3">
        <legend className="mb-1 font-medium text-sm">{t("coding")}</legend>
        <div className="flex items-center gap-2">
          <Switch
            id={`${id}-coding`}
            checked={value.coding.enabled}
            onCheckedChange={(enabled) => set("coding", { ...value.coding, enabled })}
          />
          <Label htmlFor={`${id}-coding`}>{t("codingEnabled")}</Label>
        </div>
        {value.coding.enabled ? (
          <div className="grid gap-3">
            <CheckboxGroup
              legend={t("codingLanguages")}
              options={CODING_LANGUAGES.map((language) => ({
                value: language,
                label: questions(`languages.${language}`),
              }))}
              value={value.coding.languages}
              onChange={(languages) =>
                set("coding", { ...value.coding, languages: languages as CodingLanguage[] })
              }
            />
            <div className="grid max-w-48 gap-1">
              <Label htmlFor={`${id}-coding-minutes`}>{t("codingMinutes")}</Label>
              <Input
                id={`${id}-coding-minutes`}
                type="number"
                inputMode="numeric"
                min={5}
                max={90}
                value={value.coding.minutes}
                aria-invalid={showProblems && Boolean(found.coding)}
                aria-describedby={about("coding")}
                onChange={(event) =>
                  set("coding", { ...value.coding, minutes: event.target.value })
                }
              />
            </div>
            {problem("coding")}
          </div>
        ) : null}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-proctoring`}>{t("proctoring")}</Label>
          <NativeSelect
            id={`${id}-proctoring`}
            value={value.proctoring_level}
            aria-describedby={`${id}-proctoring-hint`}
            onChange={(event) => set("proctoring_level", event.target.value as ProctoringLevel)}
            options={PROCTORING_LEVELS.map((level) => ({
              value: level,
              label: t(`levels.${level}`),
            }))}
          />
          <p id={`${id}-proctoring-hint`} className="text-muted-foreground text-xs">
            {preset === undefined
              ? t(`levelHints.${value.proctoring_level}`)
              : preset.length === 0
                ? t("presetNone")
                : t("presetChecks", {
                    checks: preset.map((check) => t(`checks.${check}` as "checks.face")).join(", "),
                  })}
          </p>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-third-eye`}>{t("thirdEye")}</Label>
          <NativeSelect
            id={`${id}-third-eye`}
            value={value.third_eye}
            onChange={(event) => set("third_eye", event.target.value as ThirdEye)}
            options={THIRD_EYE_MODES.map((mode) => ({
              value: mode,
              label: t(`thirdEyeModes.${mode}`),
            }))}
          />
        </div>
      </div>

      <fieldset className="grid gap-2">
        <legend className="mb-1 font-medium text-sm">{t("recording")}</legend>
        <div className="flex flex-wrap gap-4">
          {RECORDING.map((track) => (
            <div key={track} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-recording-${track}`}
                checked={value.recording[track]}
                onCheckedChange={(checked) =>
                  set("recording", { ...value.recording, [track]: checked === true })
                }
              />
              <Label htmlFor={`${id}-recording-${track}`} className="font-normal">
                {t(`tracks.${track}`)}
              </Label>
            </div>
          ))}
        </div>
      </fieldset>

      <fieldset
        className="grid gap-2"
        aria-invalid={showProblems && Boolean(found.rubric)}
        aria-describedby={about("rubric")}
      >
        <legend className="mb-1 font-medium text-sm">{t("rubric")}</legend>
        <p className="text-muted-foreground text-xs">{t("rubricHint")}</p>
        <div className="grid gap-3 sm:grid-cols-4">
          {RUBRIC_DIMENSIONS.map((dimension) => (
            <div key={dimension} className="grid gap-1">
              <Label htmlFor={`${id}-rubric-${dimension}`}>{t(`dimensions.${dimension}`)}</Label>
              <Input
                id={`${id}-rubric-${dimension}`}
                type="number"
                inputMode="numeric"
                min={0}
                max={100}
                value={value.rubric[dimension]}
                onChange={(event) =>
                  set("rubric", { ...value.rubric, [dimension]: event.target.value })
                }
              />
            </div>
          ))}
        </div>
        <p className="text-muted-foreground text-sm">
          {t("totalNow", { total: total(value.rubric) })}
        </p>
        {problem("rubric")}
      </fieldset>
    </fieldset>
  );
}
