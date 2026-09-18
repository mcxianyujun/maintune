import type { ReactNode } from "react";

const safeHref = (value: string) => {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? value : null;
  } catch {
    return null;
  }
};

function inline(text: string): ReactNode[] {
  const result: ReactNode[] = [];
  const pattern = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index! > offset) result.push(text.slice(offset, match.index));
    const value = match[0];
    if (value.startsWith("`")) result.push(<code key={`${match.index}-code`}>{value.slice(1, -1)}</code>);
    else if (value.startsWith("**")) result.push(<strong key={`${match.index}-strong`}>{value.slice(2, -2)}</strong>);
    else {
      const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(value)!;
      const href = safeHref(parts[2]);
      result.push(href ? <a key={`${match.index}-link`} href={href} target="_blank" rel="noreferrer noopener">{parts[1]}</a> : parts[1]);
    }
    offset = match.index! + value.length;
  }
  if (offset < text.length) result.push(text.slice(offset));
  return result;
}

export function SafeMarkdown({ source }: { source: string }) {
  const blocks: ReactNode[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) body.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre key={`code-${index}`}><code data-language={language}>{body.join("\n")}</code></pre>);
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const children = inline(heading[2]);
      const key = `heading-${index++}`;
      blocks.push(heading[1].length === 1 ? <h1 key={key}>{children}</h1> : heading[1].length === 2 ? <h2 key={key}>{children}</h2> : heading[1].length === 3 ? <h3 key={key}>{children}</h3> : <h4 key={key}>{children}</h4>);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) items.push(<li key={index}>{inline(lines[index++].replace(/^[-*]\s+/, ""))}</li>);
      blocks.push(<ul key={`list-${index}`}>{items}</ul>);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) items.push(<li key={index}>{inline(lines[index++].replace(/^\d+\.\s+/, ""))}</li>);
      blocks.push(<ol key={`ordered-${index}`}>{items}</ol>);
      continue;
    }
    if (!line.trim()) { index += 1; continue; }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+|^```|^[-*]\s+|^\d+\.\s+/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(" "))}</p>);
  }
  return <div className="markdown-body">{blocks}</div>;
}
