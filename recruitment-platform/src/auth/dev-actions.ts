"use server";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { devToolsEnabled } from "../config/environment";
import { safeNext } from "./next-path";
import { isRole } from "./permissions";
import { DEV_ROLE_COOKIE } from "./session";

/** Development sign-in: continue as one of the fixture sessions. Absent unless the tools are on. */
export async function signInAsDevRole(form: FormData): Promise<never> {
  const role = form.get("role");
  if (!devToolsEnabled() || !isRole(role)) notFound();
  (await cookies()).set(DEV_ROLE_COOKIE, role, { httpOnly: true, sameSite: "lax", path: "/" });
  const next = form.get("next");
  redirect(safeNext(typeof next === "string" ? next : null));
}

/** Signs out. SP-02 adds ending the server session; the development role always goes. */
export async function signOut(): Promise<never> {
  (await cookies()).delete(DEV_ROLE_COOKIE);
  redirect("/login");
}
