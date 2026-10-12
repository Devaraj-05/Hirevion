"use client";

import { useRouter } from "next/navigation";
import { type InterviewChoice, RequestForm } from "./request-form";

/** The request form on its page: once a request is sent, the list below it is read again. */
export function RequestsPanel(props: {
  interviews: readonly InterviewChoice[];
  initialKind?: string | null;
  initialInterview?: string | null;
}) {
  const router = useRouter();
  return <RequestForm {...props} onSent={() => router.refresh()} />;
}
