/** RFC 9457 problem details, as every Hirevion API error is shaped (ADR-0010). */

export const PROBLEM_MEDIA_TYPE = "application/problem+json";

export interface ProblemFieldError {
  detail: string;
  pointer?: string;
  parameter?: string;
  header?: string;
}

export interface ProblemBody {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  instance?: string;
  trace_id?: string | null;
  errors?: ProblemFieldError[];
  [extension: string]: unknown;
}

/** Codes for failures that didn't come from the API itself (a proxy, the network). */
const STATUS_CODES: Record<number, string> = {
  429: "rate-limited",
  500: "internal-error",
  502: "bad-gateway",
  503: "service-unavailable",
  504: "gateway-timeout",
};

/** A failed API call. Switch on `code`; quote `traceId` when reporting a problem. */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string | undefined;
  readonly traceId: string | null;
  readonly errors: ProblemFieldError[];
  readonly raw: ProblemBody;

  constructor(raw: ProblemBody) {
    super(raw.title);
    this.name = "ApiProblem";
    this.status = raw.status;
    this.code = raw.code;
    this.title = raw.title;
    this.detail = raw.detail;
    this.traceId = raw.trace_id ?? null;
    this.errors = raw.errors ?? [];
    this.raw = raw;
  }
}

export function isApiProblem(value: unknown): value is ApiProblem {
  return value instanceof ApiProblem;
}

function isProblemBody(value: unknown): value is ProblemBody {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return typeof body.code === "string" && typeof body.status === "number";
}

/** The problem a failed response describes, or one made up from its status. */
export async function problemFromResponse(response: Response): Promise<ApiProblem> {
  if (response.headers.get("content-type")?.includes(PROBLEM_MEDIA_TYPE)) {
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => undefined);
    if (isProblemBody(body)) return new ApiProblem(body);
  }
  return new ApiProblem({
    type: "about:blank",
    title: response.statusText || `HTTP ${response.status}`,
    status: response.status,
    code: STATUS_CODES[response.status] ?? `http-${response.status}`,
  });
}
