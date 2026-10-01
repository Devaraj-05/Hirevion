import { vi } from "vitest";

/** A stand-in for next/navigation in component tests (registered in vitest.setup.ts). */

export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
};

const current = { pathname: "/dashboard", search: "" };

export const nextNavigation = {
  useRouter: () => router,
  usePathname: () => current.pathname,
  useSearchParams: () => new URLSearchParams(current.search),
};

export function resetNavigation(pathname = "/dashboard", search = ""): void {
  current.pathname = pathname;
  current.search = search;
  for (const fn of Object.values(router)) fn.mockReset();
}
