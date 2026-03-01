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
      <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
    ),
    strong: ({ children }: { children?: React.ReactNode }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    em: ({ children }: { children?: React.ReactNode }) => (
      <em className="italic text-foreground/90">{children}</em>
    ),
    del: ({ children }: { children?: React.ReactNode }) => (
      <del className="line-through opacity-60">{children}</del>
    ),
    code: ({ inline, className, children, ...props }: { inline?: boolean; className?: string; children?: React.ReactNode }) => {
      const match = /language-(\w+)/.exec(className || '');
      const lang = match ? match[1] : '';
 
      if (!inline && (match || String(children).includes('\n'))) {
        return (
          <div className="my-2 rounded-terminal overflow-hidden border border-border/30">
            <div className={`flex items-center justify-between px-3 py-1 border-b border-border/30 bg-muted/40`}>
              <span className="text-[0.625rem] font-mono text-muted-foreground uppercase tracking-wider">{lang || 'code'}</span>
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
          className={`px-1.5 py-0.5 rounded-terminal text-[0.71875rem] font-mono border border-border/30 bg-muted/60 text-foreground/90`}
          {...props}
        >
          {children}
        </code>
      );
    },
    blockquote: ({ children }: { children?: React.ReactNode }) => (
      <blockquote className="border-l-2 border-foreground/20 pl-3 my-2 text-foreground/70 italic">
        {children}
      </blockquote>
    ),
    h1: ({ children }: { children?: React.ReactNode }) => (
      <h1 className="text-[0.9375rem] font-semibold mt-3 mb-1.5 first:mt-0">{children}</h1>
    ),
    h2: ({ children }: { children?: React.ReactNode }) => (
      <h2 className="text-[0.8125rem] font-semibold mt-2.5 mb-1 first:mt-0">{children}</h2>
    ),
    h3: ({ children }: { children?: React.ReactNode }) => (
      <h3 className="text-[0.75rem] font-semibold mt-2 mb-0.5 first:mt-0">{children}</h3>
    ),
    ul: ({ children }: { children?: React.ReactNode }) => (
      <ul className="list-disc pl-4 my-1.5 space-y-0.5">{children}</ul>
    ),
    ol: ({ children }: { children?: React.ReactNode }) => (
      <ol className="list-decimal pl-4 my-1.5 space-y-0.5">{children}</ol>
    ),
    li: ({ children }: { children?: React.ReactNode }) => (
      <li className="text-foreground/90">{children}</li>
    ),
    table: ({ children }: { children?: React.ReactNode }) => (
      <div className="overflow-x-auto my-2">
        <table className="w-full text-[0.71875rem] border-collapse">{children}</table>
      </div>
    ),
    thead: ({ children }: { children?: React.ReactNode }) => (
      <thead className="border-b border-border/40">{children}</thead>
    ),
    th: ({ children }: { children?: React.ReactNode }) => (
      <th className="text-left px-2.5 py-1 font-semibold text-foreground/80">{children}</th>
    ),
    td: ({ children }: { children?: React.ReactNode }) => (
      <td className="px-2.5 py-1 border-t border-border/30 text-foreground/80">{children}</td>
    ),
    hr: () => <hr className="my-3 border-border/40" />,
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent-0 underline underline-offset-2 hover:opacity-80 transition-opacity"
      >
        {children}
      </a>
    ),
  };
}
 
export function UserBubble({ event, isDark }: { event: UserMessageEvent; isDark?: boolean }) {
  const components = useMemo(() => makeMarkdownComponents(!!isDark), [isDark]);
 
  return (
    <div className="px-4 py-1.5">
      <div className="flex rounded-ui border border-border/40 bg-oxide-terminal-bg overflow-hidden">
        <div className="w-[0.1875rem] shrink-0 bg-muted-foreground" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-1">
            <span className="text-[0.6875rem] font-bold uppercase tracking-wider font-mono text-muted-foreground">
              User
            </span>
            <span className="text-[0.625rem] text-muted-foreground opacity-80 font-mono">
              {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>

          <div className="px-4 pb-3">
            <div className="text-[0.8125rem] font-mono">
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
export function AgentBubble({ event, isDark }: { event: AgentMessageEvent; isDark?: boolean }) {
  const components = useMemo(() => makeMarkdownComponents(!!isDark), [isDark]);
 
  return (
    <div className="py-1">
      <div className="text-[0.8125rem] font-mono">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {event.content}
        </ReactMarkdown>
        {event.streaming && (
          <span className="inline-block w-1.5 h-[1em] bg-current ml-0.5 animate-pulse align-middle opacity-60" />
        )}
      </div>
    </div>
  );
}