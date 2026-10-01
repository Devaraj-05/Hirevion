import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SectionTabs } from "./section-tabs";

describe("SectionTabs", () => {
  it("is a navigation of links with the current one marked", () => {
    render(
      <SectionTabs
        label="Jobs"
        tabs={[
          { href: "/jobs", label: "All", active: false },
          { href: "/jobs?status=draft", label: "Draft", active: true },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Jobs" });
    expect(within(nav).getByRole("link", { name: "Draft" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "All" })).not.toHaveAttribute("aria-current");
  });
});
