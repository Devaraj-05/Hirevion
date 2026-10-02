import { AdminDevNotice } from "@/admin/dev-notice";
import type { PageBodyProps } from "@/page/bodies";
import { RolesPanel } from "./roles/roles-panel";
import { UsersTable } from "./users/users-table";

/** The administration pages' bodies (SP-02b). Development sessions have no account behind
 * them, so they see a notice instead. */

export async function UsersBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <UsersTable />;
}

export async function RolesBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <RolesPanel held={session.permissions} />;
}
