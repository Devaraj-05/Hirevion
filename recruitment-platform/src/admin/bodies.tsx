import { Button, EmptyState } from "@hirevion/ui";
import { Building } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import type { PageBodyProps } from "@/page/bodies";
import { OrganizationsPanel } from "@/platform/organizations/organizations-panel";
import { ScreeningDefaults } from "@/screening/settings-form";
import { OrganizationForm } from "./organization/organization-form";
import { RolesPanel } from "./roles/roles-panel";
import { DepartmentsPanel } from "./structure/departments-panel";
import { TeamsPanel } from "./structure/teams-panel";
import { UsersTable } from "./users/users-table";

/** The administration and platform pages' bodies (SP-02b). Development sessions have no
 * account behind them, so they see a notice instead. */

export async function UsersBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <UsersTable />;
}

export async function RolesBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <RolesPanel held={session.permissions} />;
}

export async function OrganizationBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  if (session.organization === null) {
    // Super admins belong to the platform itself, which has no profile.
    const t = await getTranslations("admin.organization");
    return (
      <EmptyState
        icon={<Building />}
        title={t("platformTitle")}
        description={t("platformBody")}
        action={
          <Button asChild variant="secondary">
            <Link href="/platform/organizations">{t("platformLink")}</Link>
          </Button>
        }
      />
    );
  }
  return (
    <div className="grid gap-6">
      <OrganizationForm />
      <ScreeningDefaults />
    </div>
  );
}

export async function DepartmentsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <DepartmentsPanel />;
}

export async function TeamsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <TeamsPanel />;
}

export async function PlatformOrganizationsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <OrganizationsPanel />;
}
