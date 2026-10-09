import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/**
 * The administration pages' calls (ADR-0014). Failures are thrown as `ApiProblem`s; creates take
 * an `Idempotency-Key` that a form generates once per submission and reuses when it retries.
 */

type Schemas = components["schemas"];
export type OrganizationProfile = Schemas["OrganizationProfileResponse"];
export type OrganizationProfileUpdate = Schemas["OrganizationProfileUpdate"];
export type Department = Schemas["DepartmentResponse"];
export type DepartmentCreate = Schemas["DepartmentCreate"];
export type DepartmentUpdate = Schemas["DepartmentUpdate"];
export type Team = Schemas["TeamResponse"];
export type TeamCreate = Schemas["TeamCreate"];
export type TeamUpdate = Schemas["TeamUpdate"];
export type Member = Schemas["MemberResponse"];
export type User = Schemas["UserResponse"];
export type UserInvite = Schemas["UserInvite"];
export type UserUpdate = Schemas["UserUpdate"];
export type Role = Schemas["RoleResponse"];
export type RoleCreate = Schemas["RoleCreate"];
export type RoleUpdate = Schemas["RoleUpdate"];
export type CataloguePermission = Schemas["PermissionResponse"];
export type OrganizationListing = Schemas["OrganizationListingResponse"];
export type OrganizationCreate = Schemas["OrganizationCreate"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** Filters a page leaves out are `undefined`; empty ones are dropped before the request. */
export interface UserQuery {
  status?: User["status"] | undefined;
  role_id?: string | undefined;
  team_id?: string | undefined;
  q?: string | undefined;
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

export interface OrganizationQuery {
  status?: OrganizationListing["status"] | undefined;
  q?: string | undefined;
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

/** The API answers every success with a body; a missing one is a bug, not a state to handle. */
function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

function idempotent(key: string) {
  return { header: { "Idempotency-Key": key } };
}

type Defined<T> = { [K in keyof T]?: Exclude<T[K], undefined> };

function cleanQuery<T extends object>(query: T): Defined<T> {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  ) as Defined<T>;
}

// The organisation profile

export async function getOrganization(): Promise<OrganizationProfile> {
  return required((await apiClient().GET("/api/v1/organization")).data);
}

export async function updateOrganization(
  changes: OrganizationProfileUpdate,
): Promise<OrganizationProfile> {
  return required((await apiClient().PATCH("/api/v1/organization", { body: changes })).data);
}

// Departments and teams

export async function listDepartments(includeArchived = false): Promise<Department[]> {
  const { data } = await apiClient().GET("/api/v1/departments", {
    params: { query: { include_archived: includeArchived } },
  });
  return data ?? [];
}

export async function createDepartment(body: DepartmentCreate, key: string): Promise<Department> {
  return required(
    (await apiClient().POST("/api/v1/departments", { body, params: idempotent(key) })).data,
  );
}

export async function updateDepartment(id: string, changes: DepartmentUpdate): Promise<Department> {
  return required(
    (
      await apiClient().PATCH("/api/v1/departments/{department_id}", {
        params: { path: { department_id: id } },
        body: changes,
      })
    ).data,
  );
}

export async function listTeams(includeArchived = false): Promise<Team[]> {
  const { data } = await apiClient().GET("/api/v1/teams", {
    params: { query: { include_archived: includeArchived } },
  });
  return data ?? [];
}

export async function createTeam(body: TeamCreate, key: string): Promise<Team> {
  return required(
    (await apiClient().POST("/api/v1/teams", { body, params: idempotent(key) })).data,
  );
}

export async function updateTeam(id: string, changes: TeamUpdate): Promise<Team> {
  return required(
    (
      await apiClient().PATCH("/api/v1/teams/{team_id}", {
        params: { path: { team_id: id } },
        body: changes,
      })
    ).data,
  );
}

export async function listTeamMembers(teamId: string): Promise<Member[]> {
  const { data } = await apiClient().GET("/api/v1/teams/{team_id}/members", {
    params: { path: { team_id: teamId } },
  });
  return data ?? [];
}

export async function addTeamMember(teamId: string, userId: string): Promise<void> {
  await apiClient().PUT("/api/v1/teams/{team_id}/members/{user_id}", {
    params: { path: { team_id: teamId, user_id: userId } },
  });
}

export async function removeTeamMember(teamId: string, userId: string): Promise<void> {
  await apiClient().DELETE("/api/v1/teams/{team_id}/members/{user_id}", {
    params: { path: { team_id: teamId, user_id: userId } },
  });
}

// Users

export async function listUsers(query: UserQuery = {}): Promise<Page<User>> {
  return required(
    (await apiClient().GET("/api/v1/users", { params: { query: cleanQuery(query) } })).data,
  );
}

export async function inviteUser(body: UserInvite, key: string): Promise<User> {
  return required(
    (await apiClient().POST("/api/v1/users", { body, params: idempotent(key) })).data,
  );
}

export async function getUser(id: string): Promise<User> {
  return required(
    (await apiClient().GET("/api/v1/users/{user_id}", { params: { path: { user_id: id } } })).data,
  );
}

export async function updateUser(id: string, changes: UserUpdate): Promise<User> {
  return required(
    (
      await apiClient().PATCH("/api/v1/users/{user_id}", {
        params: { path: { user_id: id } },
        body: changes,
      })
    ).data,
  );
}

export async function setUserRoles(id: string, roleIds: string[]): Promise<User> {
  return required(
    (
      await apiClient().PUT("/api/v1/users/{user_id}/roles", {
        params: { path: { user_id: id } },
        body: { role_ids: roleIds },
      })
    ).data,
  );
}

export async function disableUser(id: string): Promise<User> {
  return required(
    (
      await apiClient().POST("/api/v1/users/{user_id}/disable", {
        params: { path: { user_id: id } },
      })
    ).data,
  );
}

export async function enableUser(id: string): Promise<User> {
  return required(
    (
      await apiClient().POST("/api/v1/users/{user_id}/enable", {
        params: { path: { user_id: id } },
      })
    ).data,
  );
}

export async function resendInvitation(id: string): Promise<void> {
  await apiClient().POST("/api/v1/users/{user_id}/invitation", {
    params: { path: { user_id: id } },
  });
}

export async function cancelInvitation(id: string): Promise<void> {
  await apiClient().DELETE("/api/v1/users/{user_id}", { params: { path: { user_id: id } } });
}

// Roles

export async function listRoles(): Promise<Role[]> {
  const { data } = await apiClient().GET("/api/v1/roles");
  return data ?? [];
}

export async function createRole(body: RoleCreate, key: string): Promise<Role> {
  return required(
    (await apiClient().POST("/api/v1/roles", { body, params: idempotent(key) })).data,
  );
}

export async function updateRole(id: string, changes: RoleUpdate): Promise<Role> {
  return required(
    (
      await apiClient().PATCH("/api/v1/roles/{role_id}", {
        params: { path: { role_id: id } },
        body: changes,
      })
    ).data,
  );
}

export async function deleteRole(id: string): Promise<void> {
  await apiClient().DELETE("/api/v1/roles/{role_id}", { params: { path: { role_id: id } } });
}

export async function listPermissions(): Promise<CataloguePermission[]> {
  const { data } = await apiClient().GET("/api/v1/permissions");
  return data ?? [];
}

// The platform's organisations

export async function listOrganizations(
  query: OrganizationQuery = {},
): Promise<Page<OrganizationListing>> {
  return required(
    (
      await apiClient().GET("/api/v1/platform/organizations", {
        params: { query: cleanQuery(query) },
      })
    ).data,
  );
}

export async function createOrganization(
  body: OrganizationCreate,
  key: string,
): Promise<OrganizationListing> {
  return required(
    (await apiClient().POST("/api/v1/platform/organizations", { body, params: idempotent(key) }))
      .data,
  );
}

export async function suspendOrganization(
  id: string,
  reason: string | null,
): Promise<OrganizationListing> {
  return required(
    (
      await apiClient().POST("/api/v1/platform/organizations/{organization_id}/suspend", {
        params: { path: { organization_id: id } },
        body: { reason },
      })
    ).data,
  );
}

export async function reactivateOrganization(id: string): Promise<OrganizationListing> {
  return required(
    (
      await apiClient().POST("/api/v1/platform/organizations/{organization_id}/reactivate", {
        params: { path: { organization_id: id } },
      })
    ).data,
  );
}

export async function inviteOrganizationAdmin(
  id: string,
  body: { name: string; email: string },
): Promise<void> {
  await apiClient().POST("/api/v1/platform/organizations/{organization_id}/admins", {
    params: { path: { organization_id: id } },
    body,
  });
}

/** How candidates sign in to the desktop app (SP-07c): the new-device code. */
export async function getCandidateAccess() {
  return required((await apiClient().GET("/api/v1/organization/candidate-access")).data);
}

export async function saveCandidateAccess(newDeviceOtp: boolean) {
  return required(
    (
      await apiClient().PUT("/api/v1/organization/candidate-access", {
        body: { new_device_otp: newDeviceOtp },
      })
    ).data,
  );
}
