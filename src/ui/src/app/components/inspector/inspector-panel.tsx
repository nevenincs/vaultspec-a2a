import {
  X,
  ExternalLink,
  RefreshCw,
  Copy,
  Check,
} from "lucide-react";
import { Button } from "../ui/button";
import { ScrollArea } from "../ui/scroll-area";
import { useState } from "react";
import type {
  InspectorTarget,
  ContextDocument,
} from "../../data/types";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { uiAccent } from "../../utils/palette";
import { log } from "../../utils/logger";

const copySuccessUi = uiAccent("copySuccess");

interface InspectorPanelProps {
  target: InspectorTarget;
  onClose: () => void;
  isDark?: boolean;
  onOpenDocument?: (doc: ContextDocument) => void;
}

/** Map file extension to Prism language string */
function detectLanguage(
  title: string,
  content: string,
): string {
  const ext = title.split(".").pop()?.toLowerCase();
  const extMap: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    rs: "rust",
    java: "java",
    kt: "kotlin",
    go: "go",
    c: "c",
    cpp: "cpp",
    cs: "csharp",
    rb: "ruby",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    yaml: "yaml",
    yml: "yaml",
    json: "json",
    toml: "toml",
    md: "markdown",
    mdx: "markdown",
    html: "html",
    htm: "html",
    css: "css",
    scss: "scss",
    less: "less",
    sql: "sql",
    graphql: "graphql",
    gql: "graphql",
    xml: "xml",
    svg: "xml",
    dockerfile: "docker",
    tf: "hcl",
    hcl: "hcl",
    lua: "lua",
    php: "php",
    swift: "swift",
    dart: "dart",
    r: "r",
    proto: "protobuf",
  };
  if (ext && extMap[ext]) return extMap[ext];
  if (
    content.trim().startsWith("{") ||
    content.trim().startsWith("[")
  )
    return "json";
  if (content.includes("def ") && content.includes(":"))
    return "python";
  if (content.includes("fn ") && content.includes("->"))
    return "rust";
  if (
    content.includes("public class") ||
    content.includes("import java.")
  )
    return "java";
  if (
    content.includes("import React") ||
    content.includes("export default")
  )
    return "typescript";
  return "text";
}

function isMarkdown(title: string): boolean {
  const ext = title.split(".").pop()?.toLowerCase();
  return ext === "md" || ext === "mdx";
}

function isCodeContent(
  type: ContextDocument["type"],
  title: string,
): boolean {
  if (type === "file") return true;
  const ext = title.split(".").pop()?.toLowerCase();
  return !!(
    ext &&
    [
      "ts", "tsx", "js", "jsx", "py", "rs", "java", "go",
      "c", "cpp", "sh", "json", "yaml", "toml", "sql",
      "html", "css", "rb", "kt", "swift", "dart", "php",
    ].includes(ext)
  );
}

/** Build an HTML page string for popout — rendered markdown or raw source */
function buildPopoutHtml(doc: ContextDocument, isDark: boolean): string {
  const isMd = isMarkdown(doc.title);
  if (isMd) {
    // Render markdown to a styled standalone page
    return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>${doc.title}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 48rem; margin: 2rem auto; padding: 0 1.5rem;
    color: ${isDark ? "#e2e8f0" : "#1e293b"};
    background: ${isDark ? "#0f172a" : "#ffffff"}; line-height: 1.7; }
  pre { background: ${isDark ? "#1e293b" : "#f1f5f9"}; padding: 1rem; border-radius: 0.375rem; overflow-x: auto; }
  code { font-size: 0.875rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid ${isDark ? "#334155" : "#e2e8f0"}; padding: 0.5rem 0.75rem; text-align: left; }
  blockquote { border-left: 3px solid ${isDark ? "#475569" : "#cbd5e1"}; margin-left: 0; padding-left: 1rem; color: ${isDark ? "#94a3b8" : "#64748b"}; }
  img { max-width: 100%; }
  a { color: ${isDark ? "#60a5fa" : "#2563eb"}; }
  h1,h2,h3,h4,h5,h6 { margin-top: 1.5em; }
</style>
</head><body>
<div id="content"></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>
<script>document.getElementById('content').innerHTML = marked.parse(${JSON.stringify(doc.content)});<\/script>
</body></html>`;
  }

  // Non-markdown: raw content in a <pre>
  return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>${doc.title}</title>
<style>
  body { font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
    margin: 2rem; color: ${isDark ? "#e2e8f0" : "#1e293b"};
    background: ${isDark ? "#0f172a" : "#ffffff"}; }
  pre { white-space: pre-wrap; word-wrap: break-word; font-size: 0.8125rem; line-height: 1.6; }
</style>
</head><body><pre>${doc.content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre></body></html>`;
}

// ─── Context List View ─────────────────────────────────────────────────────────
function ContextListView({
  documents,
  onClose,
  onOpenDocument,
}: {
  documents: ContextDocument[];
  onClose: () => void;
  onOpenDocument?: (doc: ContextDocument) => void;
}) {
  return (
    <div className="h-full border-l border-border bg-oxide-sidebar-bg flex flex-col animate-in slide-in-from-right-4 duration-200" role="complementary" aria-label="Plans list">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-[0.8125rem] font-semibold tracking-tight">
            Plans
          </span>
          <span className="text-[0.6875rem] text-muted-foreground">
            {documents.length}
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={onClose}
          aria-label="Close plans panel"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="px-2 py-1 space-y-0.5" role="list" aria-label="Plan documents">
          {documents.map((doc) => (
            <button
              key={doc.id}
              onClick={() => onOpenDocument?.(doc)}
              role="listitem"
              aria-label={`Open document: ${doc.title}`}
              className="w-full text-left rounded-ui px-2.5 py-2 hover:bg-accent/50 transition-colors group"
            >
              <div className="flex items-start gap-2">
                <span className="flex-1 text-[0.75rem] truncate text-foreground/80 group-hover:text-foreground transition-colors">
                  {doc.title}
                </span>
                <span className="text-[0.625rem] text-muted-foreground shrink-0 mt-0.5">
                  {new Date(doc.updated_at).toLocaleDateString([], {
                    month: "short",
                    day: "numeric",
                  })}
                </span>
              </div>
            </button>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

// ─── Document Detail View ──────────────────────────────────────────────────────
function DocumentView({
  document: doc,
  onClose,
  isDark,
}: {
  document: ContextDocument;
  onClose: () => void;
  isDark: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [viewRaw, setViewRaw] = useState(false);

  const shouldHighlight = isCodeContent(doc.type, doc.title);
  const language = shouldHighlight
    ? detectLanguage(doc.title, doc.content)
    : "text";
  const highlighterStyle = isDark ? oneDark : oneLight;
  const isMd = isMarkdown(doc.title);

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard API not available");
      await navigator.clipboard.writeText(doc.content);
      setCopied(true);
      log.debug('inspector.copy', `Copied ${doc.title} to clipboard`);
    } catch {
      try {
        const textArea = globalThis.document.createElement("textarea");
        textArea.value = doc.content;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        globalThis.document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        const successful = globalThis.document.execCommand("copy");
        if (successful) {
          setCopied(true);
          log.debug('inspector.copy', `Copied ${doc.title} via fallback`);
        }
        globalThis.document.body.removeChild(textArea);
      } catch (fallbackErr) {
        log.error('inspector.copy', `Failed to copy ${doc.title}`, fallbackErr);
      }
    }
    setTimeout(() => setCopied(false), 2000);
  };

  const handlePopout = () => {
    try {
      const html = buildPopoutHtml(doc, isDark);
      const dataUri =
        "data:text/html;charset=utf-8," + encodeURIComponent(html);
      const anchor = globalThis.document.createElement("a");
      anchor.href = dataUri;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.style.display = "none";
      globalThis.document.body.appendChild(anchor);
      anchor.click();
      globalThis.document.body.removeChild(anchor);
      log.debug('inspector.popout', `Opened ${doc.title} in new tab`);
    } catch (err) {
      log.error('inspector.popout', `Failed to open ${doc.title} in new tab`, err);
    }
  };

  return (
    <div className="h-full border-l border-border bg-oxide-sidebar-bg flex flex-col animate-in slide-in-from-right-4 duration-200 overflow-hidden">
      {/* Header — title + close only */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex flex-col min-w-0 overflow-hidden">
          <h3 className="text-[0.8125rem] font-semibold truncate leading-none mb-1">
            {doc.title}
          </h3>
          <span className="text-[0.625rem] text-muted-foreground font-mono">
            {new Date(doc.updated_at).toLocaleString()}
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 ml-2"
          onClick={onClose}
          aria-label="Close document panel"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col mx-4 mt-4 mb-4 rounded-ui border border-border shadow-sm">
          {/* Content header bar — filename + actions */}
          <div className="flex items-center justify-between px-3 py-1.5 bg-muted/40 border-b border-border shrink-0">
            <span className="text-[0.625rem] font-mono text-muted-foreground truncate min-w-0">
              {doc.title}
            </span>
            <div className="flex items-center gap-0.5 shrink-0 ml-2">
              {isMd && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-foreground"
                  onClick={() => setViewRaw(!viewRaw)}
                  title={viewRaw ? "View rendered" : "View raw"}
                  aria-label={viewRaw ? "View rendered markdown" : "View raw source"}
                >
                  <span className="text-[0.5625rem] font-mono font-bold">
                    {viewRaw ? "MD" : "</>"}
                  </span>
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={handleCopy}
                title="Copy content"
                aria-label={copied ? "Copied" : "Copy content"}
              >
                {copied ? (
                  <Check className={`h-3 w-3 ${copySuccessUi.text}`} />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={handlePopout}
                title="Open in new tab"
                aria-label="Open in new tab"
              >
                <ExternalLink className="h-3 w-3" />
              </Button>
            </div>
          </div>

          {/* Scrollable content area */}
          <ScrollArea className="flex-1 min-h-0">
            <div className="max-w-full overflow-x-hidden">
              {isMd && !viewRaw ? (
                /* Rendered markdown */
                <div className="p-4 prose prose-sm dark:prose-invert max-w-none break-words [&_pre]:overflow-x-auto [&_pre]:max-w-full [&_table]:text-[0.75rem] [&_img]:max-w-full">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {doc.content}
                  </ReactMarkdown>
                </div>
              ) : shouldHighlight && language !== "text" && language !== "markdown" ? (
                /* Syntax highlighted code */
                <SyntaxHighlighter
                  language={language}
                  style={highlighterStyle}
                  customStyle={{
                    margin: 0,
                    padding: "1rem",
                    fontSize: "0.75rem",
                    lineHeight: "1.6",
                    minHeight: "12.5rem",
                    borderRadius: 0,
                    overflowX: "auto",
                  }}
                  showLineNumbers
                  lineNumberStyle={{
                    color: "var(--muted-foreground)",
                    opacity: 0.6,
                    fontSize: "0.6875rem",
                    minWidth: "2.5em",
                    paddingRight: "1em",
                    userSelect: "none" as const,
                  }}
                  wrapLongLines
                >
                  {doc.content}
                </SyntaxHighlighter>
              ) : (
                /* Plain text / raw markdown */
                <pre className="text-[0.75rem] font-mono whitespace-pre-wrap break-words leading-relaxed text-foreground/85 p-4 bg-card min-h-[12.5rem]">
                  {doc.content}
                </pre>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Footer metadata */}
      <div className="px-4 pb-3 pt-0 shrink-0">
        <div className="flex items-center gap-3 text-[0.625rem] text-muted-foreground font-mono">
          <span>{doc.content.length.toLocaleString()} chars</span>
          <span className="opacity-40">|</span>
          <span>{doc.content.split("\n").length} lines</span>
          <span className="opacity-40">|</span>
          <span>{doc.type === "file" ? "Local" : "External"}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main InspectorPanel ───────────────────────────────────────────────────────
export function InspectorPanel({
  target,
  onClose,
  isDark = true,
  onOpenDocument,
}: InspectorPanelProps) {
  // Context list view
  if (target.type === "context_list") {
    return (
      <ContextListView
        documents={target.documents || []}
        onClose={onClose}
        onOpenDocument={onOpenDocument}
      />
    );
  }

  // Resolve the document for single-doc views
  const document =
    target.type === "document"
      ? target.document
      : ({
          id: target.event?.id || "unknown",
          title:
            target.type === "tool_call"
              ? "Tool Call"
              : target.type === "artifact"
                ? "Artifact"
                : "Plan Detail",
          content: JSON.stringify(target.event, null, 2),
          type: "note" as const,
          updated_at:
            target.event?.timestamp || new Date().toISOString(),
        } as ContextDocument);

  if (!document) return null;

  return (
    <DocumentView
      document={document}
      onClose={onClose}
      isDark={isDark}
    />
  );
}