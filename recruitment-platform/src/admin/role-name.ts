"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

/** A role's name in the reader's language: built-in roles by key, custom roles as named. */
export function useRoleName(): (role: { key?: string | null; name: string }) => string {
  const roles = useTranslations("roles");
  return useCallback(
    (role) =>
      role.key && roles.has(role.key as "recruiter") ? roles(role.key as "recruiter") : role.name,
    [roles],
  );
}
