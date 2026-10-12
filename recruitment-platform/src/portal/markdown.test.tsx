import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

const POLICY = [
  "> **Draft for legal review**, not yet in force.",
  "",
  "## Asking for deletion",
  "",
  "You can ask *at any time*:",
  "- **In the portal:** go to Requests.",
  "- **By email:** see [support](support.md) or [the board](https://example.test/board).",
  "",
  "1. **We acknowledge** it.",
  "2. **Within 30 days** we delete:",
  "   - your account;",
  "   - your recordings.",
  "",
  "| Data | Kept |",
  "|---|---|",
  "| Recordings | 90 days |",
  "",
  "### Notes",
  "Plain <script>alert(1)</script> and [a trap](javascript:alert(1)).",
].join("\n");

describe("Markdown (the policies' subset)", () => {
  it("renders headings one level below the page's", () => {
    render(<Markdown source={POLICY} idPrefix="deletion" />);
    expect(screen.getByRole("heading", { level: 3, name: "Asking for deletion" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 4, name: "Notes" })).toBeVisible();
  });

  it("renders lists, nested lists, emphasis and quotes", () => {
    const { container } = render(<Markdown source={POLICY} idPrefix="deletion" />);
    const lists = screen.getAllByRole("list");
    expect(lists.map((list) => list.tagName)).toEqual(["UL", "OL", "UL"]);
    const steps = within(lists[1] as HTMLElement).getAllByRole("listitem");
    expect(steps[1]).toHaveTextContent(
      /Within 30 days we delete:\s*your account;\s*your recordings\./,
    );
    expect(container.querySelector("blockquote strong")).toHaveTextContent(
      "Draft for legal review",
    );
    expect(container.querySelector("em")).toHaveTextContent("at any time");
  });

  it("renders tables with header cells", () => {
    render(<Markdown source={POLICY} idPrefix="deletion" />);
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Data" })).toBeVisible();
    expect(within(table).getByRole("cell", { name: "90 days" })).toBeVisible();
  });

  it("links other policies within the page and opens web links safely", () => {
    render(<Markdown source={POLICY} idPrefix="deletion" />);
    expect(screen.getByRole("link", { name: "support" })).toHaveAttribute(
      "href",
      "#policy-support",
    );
    const board = screen.getByRole("link", { name: "the board" });
    expect(board).toHaveAttribute("href", "https://example.test/board");
    expect(board).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("never renders HTML or unsafe links", () => {
    const { container } = render(<Markdown source={POLICY} idPrefix="deletion" />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/Plain <script>alert\(1\)<\/script>/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "a trap" })).toBeNull();
    expect(screen.getByText(/a trap/)).toBeVisible();
  });
});
