"use client";

import { Command } from "cmdk";
import { Dialog as DialogPrimitive } from "radix-ui";
import { useRef } from "react";

export interface CommandItem {
  id: string;
  label: string;
  keywords?: readonly string[];
  hint?: string;
  onSelect: () => void;
}

export interface CommandGroup {
  heading: string;
  items: readonly CommandItem[];
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The dialog's accessible name, e.g. "Go to". */
  label: string;
  placeholder: string;
  emptyLabel: string;
  groups: readonly CommandGroup[];
}

/** Ctrl/⌘+K: jump to any page the user may open. */
export function CommandPalette({
  open,
  onOpenChange,
  label,
  placeholder,
  emptyLabel,
  groups,
}: CommandPaletteProps) {
  // There is no Radix trigger to return focus to (a shortcut or any button opens the palette),
  // so remember what had focus when it opened and go back there when it closes.
  const returnFocusTo = useRef<Element | null>(null);
  const run = (item: CommandItem) => {
    onOpenChange(false);
    item.onSelect();
  };
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-overlay" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          onOpenAutoFocus={() => {
            returnFocusTo.current = document.activeElement;
          }}
          onCloseAutoFocus={(event) => {
            const target = returnFocusTo.current;
            if (target instanceof HTMLElement && target.isConnected) {
              event.preventDefault();
              target.focus();
            }
          }}
          className="fixed top-[15vh] left-1/2 z-50 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-surface shadow-md"
        >
          <DialogPrimitive.Title className="sr-only">{label}</DialogPrimitive.Title>
          <Command label={label}>
            <Command.Input
              placeholder={placeholder}
              className="h-11 w-full border-b border-border bg-transparent px-4 text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
            <Command.List className="max-h-80 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">
                {emptyLabel}
              </Command.Empty>
              {groups.map((group) => (
                <Command.Group
                  key={group.heading}
                  heading={group.heading}
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground"
                >
                  {group.items.map((item) => (
                    <Command.Item
                      key={item.id}
                      value={`${item.label} ${item.id}`}
                      keywords={item.keywords ? [...item.keywords] : []}
                      onSelect={() => run(item)}
                      className="flex cursor-default items-center justify-between rounded-sm px-2 py-2 text-sm text-foreground data-[selected=true]:bg-surface-muted"
                    >
                      <span>{item.label}</span>
                      {item.hint ? (
                        <span className="text-xs text-muted-foreground">{item.hint}</span>
                      ) : null}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
