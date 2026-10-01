"use client";

import { X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

interface PanelProps extends Omit<ComponentProps<typeof DialogPrimitive.Content>, "title"> {
  title: string;
  description?: string;
  /** The close button's accessible name. */
  closeLabel: string;
  footer?: ReactNode;
}

function Header({ title, description }: { title: string; description?: string | undefined }) {
  return (
    <div className="grid gap-1">
      <DialogPrimitive.Title className="text-base font-semibold text-foreground">
        {title}
      </DialogPrimitive.Title>
      {description ? (
        <DialogPrimitive.Description className="text-sm text-muted-foreground">
          {description}
        </DialogPrimitive.Description>
      ) : null}
    </div>
  );
}

function CloseButton({ label }: { label: string }) {
  return (
    <DialogPrimitive.Close
      aria-label={label}
      className="absolute top-3 right-3 rounded-sm p-1 text-muted-foreground hover:text-foreground"
    >
      <X className="size-4" aria-hidden />
    </DialogPrimitive.Close>
  );
}

const overlay = "fixed inset-0 z-40 bg-overlay";

/** A centred modal; it always has a title (and usually a description) for screen readers. */
export function DialogContent({
  title,
  description,
  closeLabel,
  footer,
  className,
  children,
  ...props
}: PanelProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlay} />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border border-border bg-surface p-6 shadow-md",
          className,
        )}
        {...(description ? {} : { "aria-describedby": undefined })}
        {...props}
      >
        <Header title={title} description={description} />
        {children}
        {footer ? <div className="flex justify-end gap-2">{footer}</div> : null}
        <CloseButton label={closeLabel} />
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;

/** A panel that slides over the page from the right (e.g. notifications). */
export function SheetContent({
  title,
  description,
  closeLabel,
  footer,
  className,
  children,
  ...props
}: PanelProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlay} />
      <DialogPrimitive.Content
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[min(24rem,100vw)] flex-col gap-4 border-l border-border bg-surface p-6 shadow-md",
          className,
        )}
        {...(description ? {} : { "aria-describedby": undefined })}
        {...props}
      >
        <Header title={title} description={description} />
        <div className="flex-1 overflow-y-auto">{children}</div>
        {footer ? <div className="flex justify-end gap-2">{footer}</div> : null}
        <CloseButton label={closeLabel} />
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
