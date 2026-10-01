import { ApiProblem } from "@hirevion/api-client";
import { toast } from "@hirevion/ui";
import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import messages from "../../messages/en-IN.json";
import { fieldErrors, useProblemToast } from "./problems";

vi.mock("@hirevion/ui", async (original) => ({
  ...(await original<typeof import("@hirevion/ui")>()),
  toast: { error: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en-IN" messages={messages} timeZone="Asia/Kolkata">
      {children}
    </NextIntlClientProvider>
  );
}

const NOT_FOUND = new ApiProblem({
  type: "urn:hirevion:problem:not-found",
  title: "Job not found",
  status: 404,
  code: "not-found",
  trace_id: "4bf92f3577b34da6",
});

beforeEach(() => {
  vi.mocked(toast.error).mockReset();
});

describe("useProblemToast", () => {
  it("names the problem and the trace id to quote", () => {
    const { result } = renderHook(() => useProblemToast(), { wrapper });
    result.current(NOT_FOUND);
    expect(toast.error).toHaveBeenCalledWith("Job not found", {
      description: "Reference: 4bf92f3577b34da6",
    });
  });

  it("falls back to a general message for anything else", () => {
    const { result } = renderHook(() => useProblemToast(), { wrapper });
    result.current(new TypeError("Failed to fetch"));
    expect(toast.error).toHaveBeenCalledWith("Something went wrong. Please try again.", {});
  });
});

describe("fieldErrors", () => {
  it("maps body pointers onto form field names", () => {
    const problem = new ApiProblem({
      type: "urn:hirevion:problem:validation-failed",
      title: "Validation failed",
      status: 422,
      code: "validation-failed",
      errors: [
        { pointer: "#/title", detail: "Required" },
        { pointer: "#/location/city", detail: "Too long" },
        { pointer: "#/a~1b", detail: "Escaped" },
        { parameter: "limit", detail: "Not a form field" },
      ],
    });
    expect(fieldErrors(problem)).toEqual({
      title: "Required",
      "location.city": "Too long",
      "a/b": "Escaped",
    });
  });
});
