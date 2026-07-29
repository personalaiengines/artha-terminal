"use client";
import { Fragment, ReactNode } from "react";
import { cn } from "@/lib/utils";

// Markdown renderer for AI answers.
//
// The analyst page previously rendered model output through `whitespace-pre-wrap`,
// so every `**bold**`, `## heading`, `|table|` and `- bullet` the model emitted
// showed up as literal punctuation. That's the single biggest reason the answers
// read as raw output rather than a finished analysis.
//
// ponytail: deliberately a subset — headings, bullets, ordered lists, tables,
// blockquotes, code, hr, and inline bold/italic/code/link. No nested lists, no
// reference links, no HTML passthrough. The system prompt in agent/chat.py
// drives the format, so the subset is the format. Swap in react-markdown if the
// output ever needs the long tail (it also means shipping remark/micromark and
// writing a component map this size anyway).

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (/^\*\*.+\*\*$/.test(part) || /^__.+__$/.test(part))
      return <strong key={key} className="font-semibold text-frost">{part.slice(2, -2)}</strong>;
    if (/^\*[^*]+\*$/.test(part))
      return <em key={key} className="italic">{part.slice(1, -1)}</em>;
    if (/^`[^`]+`$/.test(part))
      return <code key={key} className="rounded bg-void/70 px-1.5 py-0.5 font-mono text-[12.5px] text-accent hairline">{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link)
      return <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer"
        className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">{link[1]}</a>;
    return <Fragment key={key}>{part}</Fragment>;
  });
}

const isTableSep = (l: string) => /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/.test(l) && l.includes("-");
const cells = (l: string) => l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let para: string[] = [];
  let i = 0;

  const flushPara = () => {
    if (!para.length) return;
    out.push(
      <p key={`p${out.length}`} className="leading-[1.7]">{inline(para.join(" "), `p${out.length}`)}</p>
    );
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { flushPara(); i++; continue; }

    // Fenced code
    if (/^\s*```/.test(line)) {
      flushPara();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(
        <pre key={`c${out.length}`} className="overflow-x-auto rounded-[var(--radius-md)] bg-void/70 p-3 hairline">
          <code className="font-mono text-[12.5px] text-mist">{buf.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // Table — needs a header row followed by a |---|---| separator
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flushPara();
      const head = cells(line);
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(cells(lines[i++]));
      out.push(
        // Wide tables scroll inside their own box rather than widening the chat column.
        <div key={`t${out.length}`} className="overflow-x-auto rounded-[var(--radius-md)] hairline">
          <table className="w-full min-w-max text-[12.5px]">
            <thead>
              <tr className="bg-void/50">
                {head.map((h, j) => (
                  <th key={j} className={cn("px-3 py-2 font-semibold text-frost", j ? "text-right" : "text-left")}>
                    {inline(h, `th${j}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r} className="border-t border-line/60">
                  {row.map((c, j) => (
                    <td key={j} className={cn("px-3 py-2 text-mist", j ? "text-right tnum" : "text-left font-medium text-frost")}>
                      {inline(c, `td${r}-${j}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Headings
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flushPara();
      const size = ["text-[17px]", "text-[15.5px]", "text-[14px]", "text-[13px]"][h[1].length - 1];
      out.push(
        <div key={`h${out.length}`} className={cn("pt-1 font-semibold text-frost", size)}>
          {inline(h[2], `h${out.length}`)}
        </div>
      );
      i++; continue;
    }

    // Horizontal rule
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      flushPara();
      out.push(<hr key={`hr${out.length}`} className="border-line/70" />);
      i++; continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      flushPara();
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(
        <blockquote key={`q${out.length}`} className="border-l-2 border-accent/50 pl-3 text-muted">
          {inline(buf.join(" "), `q${out.length}`)}
        </blockquote>
      );
      continue;
    }

    // Lists (bulleted or numbered)
    const bullet = /^\s*[-*+]\s+/, numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      flushPara();
      const ordered = numbered.test(line) && !bullet.test(line);
      const re = ordered ? numbered : bullet;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i])) {
        let item = lines[i++].replace(re, "");
        // Fold continuation lines into the item they belong to.
        while (i < lines.length && lines[i].trim() && !bullet.test(lines[i]) &&
               !numbered.test(lines[i]) && !/^\s*(#|>|```)/.test(lines[i])) {
          item += " " + lines[i++].trim();
        }
        items.push(item);
      }
      const Tag = ordered ? "ol" : "ul";
      out.push(
        <Tag key={`l${out.length}`} className={cn("space-y-1.5 pl-5", ordered ? "list-decimal" : "list-disc",
          "marker:text-muted")}>
          {items.map((it, j) => <li key={j} className="leading-[1.65] pl-1">{inline(it, `li${j}`)}</li>)}
        </Tag>
      );
      continue;
    }

    para.push(line.trim());
    i++;
  }
  flushPara();

  return <div className={cn("space-y-3 text-[14px] text-mist", className)}>{out}</div>;
}
