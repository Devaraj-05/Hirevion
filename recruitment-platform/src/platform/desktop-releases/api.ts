import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The desktop release registry (SP-07c): channels with their minimum versions, and releases. */

type Schemas = components["schemas"];
export type ReleaseRegistry = Schemas["ReleaseRegistry"];
export type Release = Schemas["ReleaseResponse"];
export type ReleaseCreate = Schemas["ReleaseCreate"];
export type ReleaseUpdate = Schemas["ReleaseUpdate"];
export type ChannelUpdate = Schemas["ChannelUpdate"];
export type Channel = Release["channel"];

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

export const releaseKeys = { registry: ["platform", "desktop-releases"] as const };

export async function getReleaseRegistry(): Promise<ReleaseRegistry> {
  return required((await apiClient().GET("/api/v1/platform/desktop-releases")).data);
}

export async function createRelease(body: ReleaseCreate): Promise<Release> {
  return required((await apiClient().POST("/api/v1/platform/desktop-releases", { body })).data);
}

export async function updateRelease(id: string, body: ReleaseUpdate): Promise<Release> {
  return required(
    (
      await apiClient().PATCH("/api/v1/platform/desktop-releases/{release_id}", {
        params: { path: { release_id: id } },
        body,
      })
    ).data,
  );
}

export async function updateChannel(channel: Channel, body: ChannelUpdate) {
  return required(
    (
      await apiClient().PUT("/api/v1/platform/desktop-channels/{channel}", {
        params: { path: { channel } },
        body,
      })
    ).data,
  );
}
