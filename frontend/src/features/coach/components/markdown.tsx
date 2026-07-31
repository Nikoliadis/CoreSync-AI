"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils/cn";

/**
 * Renders the coach's answers.
 *
 * `react-markdown` builds a syntax tree rather than assigning to innerHTML, and
 * raw HTML is not enabled — so model output cannot inject markup into the page.
 * That matters more than usual here: the model's input includes the user's own
 * free text, which is exactly the path a prompt injection would try to use.
 */
export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 text-body text-text", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-text">{children}</strong>,
          ul: ({ children }) => (
            <ul className="ml-4 flex list-disc flex-col gap-1 marker:text-text-muted">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="ml-4 flex list-decimal flex-col gap-1 marker:text-text-muted">
              {children}
            </ol>
          ),
          h1: ({ children }) => <h3 className="text-h3 text-text">{children}</h3>,
          h2: ({ children }) => <h3 className="text-h3 text-text">{children}</h3>,
          h3: ({ children }) => <h4 className="text-body-lg font-semibold text-text">{children}</h4>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              // noreferrer as well as noopener: the destination is model-supplied
              // and should not learn where the click came from.
              rel="noopener noreferrer"
              className="text-accent-text underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ className: codeClass, children }) => {
            const isBlock = Boolean(codeClass);
            if (!isBlock) {
              return (
                <code className="rounded-sm bg-surface-well px-1.5 py-0.5 font-mono text-[0.85em] text-text">
                  {children}
                </code>
              );
            }
            return (
              <code className="block font-mono text-caption leading-relaxed text-text">
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            // Wide code scrolls inside its own box; the page never scrolls
            // sideways (docs/09 §9).
            <pre className="overflow-x-auto rounded-md border border-border bg-surface-well p-3">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-caption">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-border px-2 py-1.5 text-left text-overline uppercase text-text-muted">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="tabular border-b border-border px-2 py-1.5 text-text-secondary">
              {children}
            </td>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-accent pl-3 text-text-secondary">
              {children}
            </blockquote>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
