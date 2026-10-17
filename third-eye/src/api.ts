/**
 * The phone's two calls (`docs/api/contracts/third-eye.md`): redeem the QR code's token once,
 * and rejoin with the device secret after a lock outlived the LiveKit token. Both go to this
 * page's own origin, which proxies `/api/v1/third-eye/*` to the API.
 */

export interface JoinResponse {
  pairing_id: string;
  livekit_url: string | null;
  participant_token: string;
  participant_identity: string;
  expires_at: string;
  device_token: string | null;
  interview: { company: string; job_title: string };
  placement: { distance_m: number; angle: string; show: string[] };
}

const MESSAGES: Record<string, string> = {
  "token-used": "This QR code was already used. Show a new one on the interview computer.",
  "token-expired": "This QR code has expired. Show a new one on the interview computer.",
  "pairing-revoked": "This pairing was cancelled. Scan the new QR code on the interview computer.",
  "pairing-not-found": "This link isn't valid. Scan the QR code on the interview computer again.",
  "interview-not-open": "This interview isn't open now.",
};
const UNAVAILABLE = "The camera service isn't reachable. Check the Wi-Fi and try again.";
/** Codes after which retrying can't help: the phone needs a new QR code. */
const FINAL = new Set(["token-used", "token-expired", "pairing-revoked", "pairing-not-found"]);

export class PairingError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly final: boolean,
  ) {
    super(message);
    this.name = "PairingError";
  }
}

async function post(path: string, body: unknown, fetcher: typeof fetch): Promise<JoinResponse> {
  let answer: Response;
  try {
    answer = await fetcher(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    throw new PairingError("network", UNAVAILABLE, false);
  }
  if (answer.ok) {
    return (await answer.json()) as JoinResponse;
  }
  const problem = (await answer.json().catch(() => ({}))) as { code?: string };
  const code = problem.code ?? `http-${answer.status}`;
  throw new PairingError(code, MESSAGES[code] ?? UNAVAILABLE, FINAL.has(code));
}

export function redeem(
  token: string,
  userAgent: string,
  fetcher: typeof fetch = fetch,
): Promise<JoinResponse> {
  return post("/api/v1/third-eye/redeem", { token, device: { user_agent: userAgent } }, fetcher);
}

export function rejoin(deviceToken: string, fetcher: typeof fetch = fetch): Promise<JoinResponse> {
  return post("/api/v1/third-eye/rejoin", { device_token: deviceToken }, fetcher);
}

/** Whether a LiveKit token (`expires_at`) still has a minute left to join with. */
export function stillValid(expiresAt: string, now: number = Date.now()): boolean {
  const expires = Date.parse(expiresAt);
  return Number.isFinite(expires) && expires - now > 60_000;
}

/** Where to reach LiveKit: the server's address, or this page's origin (which proxies /rtc). */
export function roomUrl(livekitUrl: string | null, host: string): string {
  return livekitUrl ?? `wss://${host}`;
}
