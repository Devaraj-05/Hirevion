import type { ReactNode } from "react";

/**
 * A small Markdown renderer for the policies in `docs/policies/` (PRD §83): headings, paragraphs,
 * lists (one level of nesting), quotes, tables, bold, italics, code and links. It builds React
 * elements, never HTML, so nothing in a policy can inject markup. Links to another policy
 * (`support.md`) jump to it on the page; web and mail links open as links; any other scheme is
 * shown as plain text.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "quote"; lines: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "list"; ordered: boolean; items: ListItem[] };

interface ListItem {
  text: string;
  children: { ordered: boolean; items: string[] } | null;
}

const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const TABLE_SEPARATOR = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    HEADING.test(line) ||
    line.startsWith(">") ||
    LIST_ITEM.test(line) ||
    (line.trim().startsWith("|") && next !== undefined && TABLE_SEPARATOR.test(next.trim()))
  );
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    const next = lines[index + 1];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1]?.length ?? 2, text: heading[2] ?? "" });
      index += 1;
      continue;
    }
    if (line.startsWith(">")) {
      const quoted: string[] = [];
      while (index < lines.length && (lines[index] ?? "").startsWith(">")) {
        quoted.push((lines[index] ?? "").replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ kind: "quote", lines: quoted });
      continue;
    }
    if (line.trim().startsWith("|") && next !== undefined && TABLE_SEPARATOR.test(next.trim())) {
      const header = cells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && (lines[index] ?? "").trim().startsWith("|")) {
        rows.push(cells(lines[index] ?? ""));
        index += 1;
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const first = line.match(LIST_ITEM);
    if (first && !first[1]) {
      const items: ListItem[] = [];
      while (index < lines.length) {
        const current = lines[index] ?? "";
        const item = current.match(LIST_ITEM);
        if (item && !item[1]) {
          items.push({ text: item[3] ?? "", children: null });
        } else if (item) {
          const parent = items.at(-1);
          if (parent) {
            parent.children ??= { ordered: /\d/.test(item[2] ?? ""), items: [] };
            parent.children.items.push(item[3] ?? "");
          }
        } else if (current.trim() && /^\s+/.test(current) && items.length > 0) {
          const parent = items.at(-1) as ListItem;
          parent.text = `${parent.text} ${current.trim()}`;
        } else {
          break;
        }
        index += 1;
      }
      blocks.push({ kind: "list", ordered: /\d/.test(first[2] ?? ""), items });
      continue;
    }
    const paragraph: string[] = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      (lines[index] ?? "").trim() &&
      !startsBlock(lines[index] ?? "", lines[index + 1])
    ) {
      paragraph.push((lines[index] ?? "").trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
  }
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\((?:[^()\s]|\([^()\s]*\))+\))/;

/** Where a link may go: another policy on this page, the web, or an email address. */
export function safeHref(href: string): string | null {
  const policy = href.match(/^([a-z-]+)\.md(#.*)?$/);
  if (policy) return `#policy-${policy[1]}`;
  if (/^https?:\/\//i.test(href) || /^mailto:/i.test(href)) return href;
  if (href.startsWith("#")) return href;
  return null;
}

function inline(text: string, key = "i"): ReactNode[] {
  const parts = text.split(INLINE);
  return parts.map((part, index) => {
    const id = `${key}-${index}`;
    if (index % 2 === 0) return part;
    if (part.startsWith("**")) return <strong key={id}>{inline(part.slice(2, -2), id)}</strong>;
    if (part.startsWith("`")) return <code key={id}>{part.slice(1, -1)}</code>;
    if (part.startsWith("[")) {
      const match = part.match(/^\[([^\]]+)\]\((.+)\)$/);
      const label = match?.[1] ?? part;
      const href = match ? safeHref(match[2] ?? "") : null;
      if (!href) return <span key={id}>{inline(label, id)}</span>;
      const external = /^https?:/i.test(href);
      return (
        <a
          key={id}
          href={href}
          className="font-medium text-primary underline underline-offset-2"
          {...(external ? { rel: "noopener noreferrer", target: "_blank" } : {})}
        >
          {inline(label, id)}
        </a>
      );
    }
    return <em key={id}>{inline(part.slice(1, -1), id)}</em>;
  });
}

function heading(level: number, text: string, key: string): ReactNode {
  // The page has its h1 and each policy's title is an h2, so "##" is an h3.
  const shifted = Math.min(level + 1, 6);
  const children = inline(text, key);
  const style = "mt-4 font-semibold";
  if (shifted <= 3)
    return (
      <h3 key={key} className={`${style} text-base`}>
        {children}
      </h3>
    );
  if (shifted === 4)
    return (
      <h4 key={key} className={`${style} text-sm`}>
        {children}
      </h4>
    );
  if (shifted === 5)
    return (
      <h5 key={key} className={`${style} text-sm`}>
        {children}
      </h5>
    );
  return (
    <h6 key={key} className={`${style} text-sm`}>
      {children}
    </h6>
  );
}

function list(ordered: boolean, items: ReactNode[], key: string): ReactNode {
  const style = ordered ? "list-decimal" : "list-disc";
  const className = `${style} grid gap-1 pl-6`;
  return ordered ? (
    <ol key={key} className={className}>
      {items}
    </ol>
  ) : (
    <ul key={key} className={className}>
      {items}
    </ul>
  );
}

function render(block: Block, key: string): ReactNode {
  switch (block.kind) {
    case "heading":
      return heading(block.level, block.text, key);
    case "paragraph":
      return <p key={key}>{inline(block.text, key)}</p>;
    case "quote":
      return (
        <blockquote key={key} className="border-border border-l-4 pl-3 text-muted-foreground">
          {block.lines.map((line, index) => {
            const id = `${key}-${index}`;
            return <p key={id}>{inline(line, id)}</p>;
          })}
        </blockquote>
      );
    case "table":
      return (
        <div key={key} className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                {block.header.map((cell, index) => {
                  const id = `${key}-h${index}`;
                  return (
                    <th key={id} scope="col" className="border-border border-b p-2">
                      {inline(cell, id)}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => {
                const rowId = `${key}-r${rowIndex}`;
                return (
                  <tr key={rowId}>
                    {row.map((cell, index) => {
                      const id = `${rowId}-${index}`;
                      return (
                        <td key={id} className="border-border border-b p-2 align-top">
                          {inline(cell, id)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      );
    case "list":
      return list(
        block.ordered,
        block.items.map((item, index) => {
          const id = `${key}-${index}`;
          return (
            <li key={id}>
              {inline(item.text, id)}
              {item.children
                ? list(
                    item.children.ordered,
                    item.children.items.map((child, childIndex) => {
                      const childId = `${id}-${childIndex}`;
                      return <li key={childId}>{inline(child, childId)}</li>;
                    }),
                    `${id}-children`,
                  )
                : null}
            </li>
          );
        }),
        key,
      );
  }
}

export function Markdown({ source, idPrefix }: { source: string; idPrefix: string }) {
  return (
    <div className="grid gap-3 text-sm leading-relaxed">
      {parseBlocks(source).map((block, index) => render(block, `${idPrefix}-${index}`))}
    </div>
  );
}
