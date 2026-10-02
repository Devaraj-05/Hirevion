import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { Badge, SeverityBadge } from "./badge";
import { Breadcrumbs } from "./breadcrumbs";
import { Button, IconButton } from "./button";
import { NativeSelect } from "./choice";
import { EmptyState } from "./empty-state";
import { KpiTile } from "./kpi-tile";

describe("Button", () => {
  it("renders each variant as a real button and forwards its ref", async () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    render(
      <>
        <Button ref={ref} onClick={onClick}>
          {"Save"}
        </Button>
        <Button variant="danger">{"Delete"}</Button>
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute("type", "button");
  });

  it("can render as a link", () => {
    render(
      <Button asChild>
        <a href="/jobs">{"Jobs"}</a>
      </Button>,
    );
    expect(screen.getByRole("link", { name: "Jobs" })).toHaveAttribute("href", "/jobs");
  });
});

describe("IconButton", () => {
  it("is named by its label", () => {
    render(<IconButton label="Notifications" icon={<svg />} />);
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("can't be created without a label", () => {
    // @ts-expect-error: an icon-only button must have an accessible name
    render(<IconButton icon={<svg />} />);
  });
});

describe("Badge", () => {
  it("shows severity as text, not only colour", () => {
    render(<SeverityBadge severity="CRITICAL" label="Critical" />);
    const badge = screen.getByText("Critical");
    expect(badge).toHaveAttribute("data-severity", "CRITICAL");
  });

  it("renders tones", () => {
    render(<Badge tone="success">{"Shortlisted"}</Badge>);
    expect(screen.getByText("Shortlisted")).toHaveAttribute("data-tone", "success");
  });
});

describe("KpiTile", () => {
  it("shows a value", () => {
    render(<KpiTile label="Open jobs" value={24} noDataLabel="no data yet" />);
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("Open jobs")).toBeInTheDocument();
  });

  it("is a term and its definition", () => {
    render(<KpiTile label="Open jobs" value={24} noDataLabel="no data yet" />);
    expect(screen.getByRole("term")).toHaveTextContent("Open jobs");
    expect(screen.getByRole("definition")).toHaveTextContent("24");
  });

  it("says when there is no data yet, showing a dash to sighted users", () => {
    render(<KpiTile label="Open jobs" value={null} noDataLabel="no data yet" />);
    expect(screen.getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("no data yet")).toHaveClass("sr-only");
    expect(screen.getByRole("definition")).toHaveTextContent("no data yet");
  });
});

describe("EmptyState", () => {
  it("has a heading, a description and an action", () => {
    render(
      <EmptyState
        title="No jobs yet"
        description="Jobs arrive with SP-04."
        action={<Button>{"Create job"}</Button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "No jobs yet" })).toBeInTheDocument();
    expect(screen.getByText("Jobs arrive with SP-04.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create job" })).toBeInTheDocument();
  });
});

describe("Breadcrumbs", () => {
  it("marks the current page", () => {
    render(
      <Breadcrumbs
        label="Breadcrumb"
        items={[
          { label: "Administration", href: "/admin" },
          { label: "Users", href: "/admin/users" },
        ]}
      />,
    );
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Administration" })).toHaveAttribute("href", "/admin");
    expect(screen.getByText("Users")).toHaveAttribute("aria-current", "page");
  });
});

describe("NativeSelect", () => {
  it("is a labelled native select that reports the chosen value", async () => {
    const onChange = vi.fn();
    render(
      <>
        <label htmlFor="zone">Time zone</label>
        <NativeSelect
          id="zone"
          value="Asia/Kolkata"
          onChange={(event) => onChange(event.target.value)}
          options={[
            { value: "Asia/Kolkata", label: "Asia/Kolkata" },
            { value: "Europe/London", label: "Europe/London" },
          ]}
        />
      </>,
    );
    const select = screen.getByRole("combobox", { name: "Time zone" });
    expect(select).toHaveDisplayValue("Asia/Kolkata");
    await userEvent.selectOptions(select, "Europe/London");
    expect(onChange).toHaveBeenCalledWith("Europe/London");
  });
});
