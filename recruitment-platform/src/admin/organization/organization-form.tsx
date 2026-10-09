"use client";

import {
  Button,
  Card,
  CardContent,
  Form,
  FormField,
  Input,
  Label,
  NativeSelect,
  Select,
  Skeleton,
  toast,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useId, useMemo } from "react";
import { type Control, type FieldValues, useForm, useFormState } from "react-hook-form";
import {
  getOrganization,
  type OrganizationProfile,
  type OrganizationProfileUpdate,
  updateOrganization,
} from "@/admin/api";
import { useAdminProblem } from "@/admin/problems";
import { keys } from "@/admin/queries";
import { z } from "@/config/zod";
import { COUNTRY_CODES } from "./countries";
import { timeZoneOptions } from "./time-zones";

const LOCALES = ["en-IN", "en-US"] as const;

/** PRD §9 "Organization profile": name, website, country, time zone and default language. */
export function OrganizationForm() {
  const common = useTranslations("admin.common");
  const profile = useQuery({ queryKey: keys.organization, queryFn: getOrganization });
  if (profile.isError) {
    return (
      <p role="alert" className="text-danger text-sm">
        {common("loadFailed")}
      </p>
    );
  }
  if (!profile.data) return <Skeleton className="h-80 w-full max-w-2xl" />;
  return <ProfileForm profile={profile.data} />;
}

function ProfileForm({ profile }: { profile: OrganizationProfile }) {
  const t = useTranslations("admin.organization");
  const common = useTranslations("admin.common");
  const locale = useLocale();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const slugId = useId();

  const countries = useMemo(() => {
    const names = new Intl.DisplayNames([locale], { type: "region" });
    return COUNTRY_CODES.map((code) => ({ value: code, label: names.of(code) ?? code })).sort(
      (a, b) => a.label.localeCompare(b.label, locale),
    );
  }, [locale]);
  const zones = useMemo(
    () => timeZoneOptions(profile.timezone).map((zone) => ({ value: zone, label: zone })),
    [profile.timezone],
  );

  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, t("nameRequired")),
        website: z.string().trim(),
        support_email: z.string().trim(),
        country: z.string(),
        timezone: z.string(),
        default_locale: z.enum(LOCALES),
      }),
    [t],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: profile.name,
      website: profile.website ?? "",
      support_email: profile.support_email ?? "",
      country: profile.country,
      timezone: profile.timezone,
      default_locale: profile.default_locale,
    },
  });

  async function submit(values: Values) {
    // Only what differs from the saved profile (the form's defaults, renewed after each save).
    const baseline = form.formState.defaultValues ?? {};
    const changes: OrganizationProfileUpdate = {};
    if (values.name !== baseline.name) changes.name = values.name;
    if (values.website !== baseline.website) changes.website = values.website || null;
    if (values.support_email !== baseline.support_email) {
      changes.support_email = values.support_email || null;
    }
    if (values.country !== baseline.country) changes.country = values.country;
    if (values.timezone !== baseline.timezone) changes.timezone = values.timezone;
    if (values.default_locale !== baseline.default_locale) {
      changes.default_locale = values.default_locale;
    }
    try {
      const saved = await updateOrganization(changes);
      queryClient.setQueryData(keys.organization, saved);
      form.reset({
        name: saved.name,
        website: saved.website ?? "",
        support_email: saved.support_email ?? "",
        country: saved.country,
        timezone: saved.timezone,
        default_locale: saved.default_locale,
      });
      toast.success(t("saved"), {});
    } catch (error) {
      const placed = problems.onForm(form, error, {
        name: "name",
        website: "website",
        support_email: "support_email",
        country: "country",
        timezone: "timezone",
        default_locale: "default_locale",
      });
      if (!placed) problems.show(error);
    }
  }

  return (
    <Card className="max-w-2xl">
      <CardContent className="pt-6">
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="name"
            label={t("name")}
            render={(field) => <Input autoComplete="organization" {...field} />}
          />
          <div className="grid gap-1.5">
            <Label htmlFor={slugId}>{t("slug")}</Label>
            <Input
              id={slugId}
              value={profile.slug}
              readOnly
              aria-describedby={`${slugId}-hint`}
              className="bg-surface-muted"
            />
            <p id={`${slugId}-hint`} className="text-muted-foreground text-sm">
              {t("slugHint")}
            </p>
          </div>
          <FormField
            control={form.control}
            name="website"
            label={t("website")}
            description={t("websiteHint")}
            render={(field) => <Input type="url" autoComplete="url" {...field} />}
          />
          <FormField
            control={form.control}
            name="support_email"
            label={t("supportEmail")}
            description={t("supportEmailHint")}
            render={(field) => <Input type="email" autoComplete="email" {...field} />}
          />
          <FormField
            control={form.control}
            name="country"
            label={t("country")}
            render={(field) => <NativeSelect options={countries} {...field} />}
          />
          <FormField
            control={form.control}
            name="timezone"
            label={t("timezone")}
            description={t("timezoneHint")}
            render={(field) => <NativeSelect options={zones} {...field} />}
          />
          <FormField
            control={form.control}
            name="default_locale"
            label={t("language")}
            description={t("languageHint")}
            render={(field) => (
              <Select
                id={field.id}
                aria-label={t("language")}
                aria-invalid={field["aria-invalid"]}
                options={LOCALES.map((value) => ({
                  value,
                  label: common(`languages.${value}`),
                }))}
                value={field.value}
                onValueChange={field.onChange}
              />
            )}
          />
          <SaveButton control={form.control} label={t("save")} />
        </Form>
      </CardContent>
    </Card>
  );
}

/** Enabled once something changed. It alone follows the form's state, so typing re-renders
 * only the field being typed in, not the long country and time-zone lists. */
function SaveButton<T extends FieldValues>({
  control,
  label,
}: {
  control: Control<T>;
  label: string;
}) {
  const { isDirty, isSubmitting } = useFormState({ control });
  return (
    <div>
      <Button type="submit" disabled={!isDirty || isSubmitting}>
        {label}
      </Button>
    </div>
  );
}
