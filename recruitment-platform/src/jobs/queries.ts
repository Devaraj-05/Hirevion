"use client";

import { useQuery } from "@tanstack/react-query";
import { getJob, getJobChoices } from "./api";

/** Query keys of the jobs pages; a change invalidates its list's prefix. */
export const keys = {
  jobs: ["jobs"] as const,
  list: ["jobs", "list"] as const,
  job: (id: string) => ["jobs", "detail", id] as const,
  versions: (id: string) => ["jobs", "detail", id, "versions"] as const,
  description: (id: string) => ["jobs", "detail", id, "description"] as const,
  choices: ["jobs", "choices"] as const,
  skills: (q: string) => ["skills", q] as const,
};

export function useJob(id: string) {
  return useQuery({ queryKey: keys.job(id), queryFn: () => getJob(id) });
}

export function useJobChoices() {
  return useQuery({ queryKey: keys.choices, queryFn: getJobChoices, staleTime: 60_000 });
}
