"use client";

import { useQuery } from "@tanstack/react-query";
import { listDepartments, listRoles, listTeams } from "./api";

/** Query keys of the administration pages; a change invalidates its list's prefix. */
export const keys = {
  users: ["admin", "users"] as const,
  user: (id: string) => ["admin", "users", "detail", id] as const,
  roles: ["admin", "roles"] as const,
  permissions: ["admin", "permissions"] as const,
  teams: ["admin", "teams"] as const,
  teamMembers: (id: string) => ["admin", "teams", "members", id] as const,
  departments: ["admin", "departments"] as const,
  organization: ["admin", "organization"] as const,
  organizations: ["platform", "organizations"] as const,
};

export function useRoles() {
  return useQuery({ queryKey: keys.roles, queryFn: listRoles });
}

export function useTeams(includeArchived = false) {
  return useQuery({
    queryKey: [...keys.teams, { includeArchived }],
    queryFn: () => listTeams(includeArchived),
  });
}

export function useDepartments(includeArchived = false) {
  return useQuery({
    queryKey: [...keys.departments, { includeArchived }],
    queryFn: () => listDepartments(includeArchived),
  });
}
