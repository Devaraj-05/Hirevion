import { zodResolver } from "@hookform/resolvers/zod";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { Button } from "./button";
import { CommandPalette } from "./command-palette";
import { Dialog, DialogContent, DialogTrigger } from "./dialog";
import { Form, FormField } from "./form";
import { Input } from "./input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

const schema = z.object({ email: z.email("Enter a valid email address") });

function SignUp({ onSubmit }: { onSubmit: (values: z.infer<typeof schema>) => void }) {
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  });
  return (
    <Form form={form} onSubmit={onSubmit}>
      <FormField
        control={form.control}
        name="email"
        label="Work email"
        description="We send the invitation here."
        render={(field) => <Input {...field} />}
      />
      <Button type="submit">{"Continue"}</Button>
    </Form>
  );
}

describe("FormField", () => {
  it("labels the control and describes it", () => {
    render(<SignUp onSubmit={vi.fn()} />);
    const input = screen.getByLabelText("Work email");
    expect(input).toHaveAccessibleDescription("We send the invitation here.");
    expect(input).toHaveAttribute("aria-invalid", "false");
  });

  it("shows the zod message after submit and links it to the control", async () => {
    const onSubmit = vi.fn();
    render(<SignUp onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Work email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    const input = screen.getByLabelText("Work email");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid email address");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/Enter a valid email address/);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("Dialog", () => {
  it("traps focus and returns it to the trigger", async () => {
    render(
      <Dialog>
        <DialogTrigger asChild>
          <Button>{"Invite"}</Button>
        </DialogTrigger>
        <DialogContent
          title="Invite a recruiter"
          description="They get an email."
          closeLabel="Close"
        >
          <Input aria-label="Email" />
        </DialogContent>
      </Dialog>,
    );
    const trigger = screen.getByRole("button", { name: "Invite" });
    await userEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Invite a recruiter" });
    expect(dialog).toHaveAccessibleDescription("They get an email.");
    for (let i = 0; i < 4; i++) {
      await userEvent.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

describe("Tabs", () => {
  it("move with the arrow keys", async () => {
    render(
      <Tabs defaultValue="open">
        <TabsList label="Job status">
          <TabsTrigger value="open">{"Open"}</TabsTrigger>
          <TabsTrigger value="closed">{"Closed"}</TabsTrigger>
        </TabsList>
        <TabsContent value="open">{"Open jobs"}</TabsContent>
        <TabsContent value="closed">{"Closed jobs"}</TabsContent>
      </Tabs>,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Open" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Closed" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Closed jobs");
  });
});

describe("CommandPalette", () => {
  it("filters items and runs the chosen one", async () => {
    const goJobs = vi.fn();
    const goCandidates = vi.fn();
    render(
      <CommandPalette
        open
        onOpenChange={vi.fn()}
        label="Go to"
        placeholder="Search pages"
        emptyLabel="Nothing found"
        groups={[
          {
            heading: "Pages",
            items: [
              { id: "jobs", label: "Jobs", onSelect: goJobs },
              { id: "candidates", label: "Candidates", onSelect: goCandidates },
            ],
          },
        ]}
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Go to" });
    await userEvent.type(within(dialog).getByPlaceholderText("Search pages"), "cand");
    expect(within(dialog).queryByText("Jobs")).not.toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(goCandidates).toHaveBeenCalledOnce();
    expect(goJobs).not.toHaveBeenCalled();
  });

  // It has no Radix trigger (a shortcut or any button opens it), so it must remember the focus.
  it("returns focus to where it was when it closes", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Search</Button>
          <CommandPalette
            open={open}
            onOpenChange={setOpen}
            label="Go to"
            placeholder="Search pages"
            emptyLabel="Nothing found"
            groups={[]}
          />
        </>
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByRole("dialog", { name: "Go to" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Search" })).toHaveFocus();
  });
});
