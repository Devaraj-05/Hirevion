import type { Briefing, ConsentBody } from "../native/commands";

/**
 * One agreement to the Terms and Conditions accepts every item of the notice (product-owner
 * decision, 2026-11-15: a checkbox per item was a stressful list of ticks). The items stay
 * listed in the Terms and Conditions, and the server still records each one.
 */
export function agreeToTerms(notice: Briefing["notice"]): ConsentBody {
  return {
    notice_version: notice.version,
    items: notice.items.map((item) => ({ purpose: item.purpose, accepted: true })),
  };
}
