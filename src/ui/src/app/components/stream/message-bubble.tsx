import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { UserMessageEvent, AgentMessageEvent } from '../../data/types';

/** Build markdown components with the correct syntax highlight style */
function makeMarkdownComponents(isDark: boolean) {
  const highlightStyle = isDark ? oneDark : oneLight;

  return {
    p: ({ children }: { children?: React.ReactNode }) => (
      <p className="mb-2 leading-relaxed last:mb-0">{children}</p>
    ),
    strong: ({ children }: { children?: React.ReactNode }) => (
      <strong className="text-foreground font-semibold">{children}</strong>
    ),
    em: ({ children }: { children?: React.ReactNode }) => (
      <em className="text-foreground/90 italic">{children}</em>
    ),
    del: ({ children }: { children?: React.ReactNode }) => (
      <del className="line-through opacity-60">{children}</del>
    ),
    code: ({
      inline,
      className,
      children,
      ...props
    }: {
      inline?: boolean;
      className?: string;
      children?: React.ReactNode;
    }) => {
      const match = /language-(\w+)/.exec(className || '');
      const lang = match ? match[1] : '';

      if (!inline && (match || String(children).includes('\n'))) {
        return (
          <div className="rounded-terminal border-border/30 my-2 overflow-hidden border">
            <div
              className={`border-border/30 bg-muted/40 flex items-center justify-between border-b px-3 py-1`}
            >
              <span className="text-muted-foreground font-mono text-[0.625rem] tracking-wider uppercase">
                {lang || 'code'}
              </span>
            </div>
            <SyntaxHighlighter
              language={lang || 'text'}
              style={highlightStyle}
              customStyle={{
                margin: 0,
                padding: '0.75rem 1rem',
                fontSize: '0.71875rem',
                lineHeight: '1.6',
                borderRadius: 0,
              }}
              wrapLongLines
            >
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          </div>
        );
      }

      return (
        <code
          className={`rounded-terminal border-border/30 bg-muted/60 text-foreground/90 border px-1.5 py-0.5 font-mono text-[0.71875rem]`}
          {...props}
        >
          {children}
        </code>
      );
    },
    blockquote: ({ children }: { children?: React.ReactNode }) => (
      <blockquote className="border-foreground/20 text-foreground/70 my-2 border-l-2 pl-3 italic">
        {children}
      </blockquote>
    ),
    h1: ({ children }: { children?: React.ReactNode }) => (
      <h1 className="mt-3 mb-1.5 text-[0.9375rem] font-semibold first:mt-0">
        {children}
      </h1>
    ),
    h2: ({ children }: { children?: React.ReactNode }) => (
      <h2 className="mt-2.5 mb-1 text-[0.8125rem] font-semibold first:mt-0">
        {children}
      </h2>
    ),
    h3: ({ children }: { children?: React.ReactNode }) => (
      <h3 className="mt-2 mb-0.5 text-[0.75rem] font-semibold first:mt-0">
        {children}
      </h3>
    ),
    ul: ({ children }: { children?: React.ReactNode }) => (
      <ul className="my-1.5 list-disc space-y-0.5 pl-4">{children}</ul>
    ),
    ol: ({ children }: { children?: React.ReactNode }) => (
      <ol className="my-1.5 list-decimal space-y-0.5 pl-4">{children}</ol>
    ),
    li: ({ children }: { children?: React.ReactNode }) => (
      <li className="text-foreground/90">{children}</li>
    ),
    table: ({ children }: { children?: React.ReactNode }) => (
      <div className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-[0.71875rem]">{children}</table>
      </div>
    ),
    thead: ({ children }: { children?: React.ReactNode }) => (
      <thead className="border-border/40 border-b">{children}</thead>
    ),
    th: ({ children }: { children?: React.ReactNode }) => (
      <th className="text-foreground/80 px-2.5 py-1 text-left font-semibold">
        {children}
      </th>
    ),
    td: ({ children }: { children?: React.ReactNode }) => (
      <td className="border-border/30 text-foreground/80 border-t px-2.5 py-1">
        {children}
      </td>
    ),
    hr: () => <hr className="border-border/40 my-3" />,
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent-0 underline underline-offset-2 transition-opacity hover:opacity-80"
      >
        {children}
      </a>
    ),
  };
}

export function UserBubble({
  event,
  isDark,
}: {
  event: UserMessageEvent;
  isDark?: boolean;
}) {
  const components = useMemo(() => makeMarkdownComponents(!!isDark), [isDark]);

  return (
    <div className="px-4 py-1.5">
      <div className="rounded-ui border-border/40 bg-oxide-terminal-bg flex overflow-hidden border">
        <div className="bg-muted-foreground w-[0.1875rem] shrink-0" />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-1">
            <span className="text-muted-foreground font-mono text-[0.6875rem] font-bold tracking-wider uppercase">
              User
            </span>
            <span className="text-muted-foreground font-mono text-[0.625rem] opacity-80">
              {new Date(event.timestamp).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>

          <div className="px-4 pb-3">
            <div className="font-mono text-[0.8125rem]">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
                {event.content}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Agent message — no icon, rendered inside a capsule. Full-width content. */
export function AgentBubble({
  event,
  isDark,
}: {
  event: AgentMessageEvent;
  isDark?: boolean;
}) {
  const components = useMemo(() => makeMarkdownComponents(!!isDark), [isDark]);

  return (
    <div className="py-1">
      <div className="font-mono text-[0.8125rem]">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {event.content}
        </ReactMarkdown>
        {event.streaming && (
          <span className="ml-0.5 inline-block h-[1em] w-1.5 animate-pulse bg-current align-middle opacity-60" />
        )}
      </div>
    </div>
  );
}
