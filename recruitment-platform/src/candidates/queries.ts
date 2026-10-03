"use client";

/** Query keys of the candidates pages and the job page's resume tabs. */
export const keys = {
  candidates: ["candidates"] as const,
  list: ["candidates", "list"] as const,
  candidate: (id: string) => ["candidates", "detail", id] as const,
  resumes: (jobId: string) => ["jobs", "detail", jobId, "resumes"] as const,
  applications: (jobId: string) => ["jobs", "detail", jobId, "applications"] as const,
};
