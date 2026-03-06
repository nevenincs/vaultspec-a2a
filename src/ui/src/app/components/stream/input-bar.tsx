import { useState, useRef, useCallback, useMemo } from 'react';
import {
  Send,
  Pause,
  ChevronDown,
  Users,
  GitBranch,
  FolderGit2,
  Tag,
  Plus,
  Check,
} from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover';
import type { AgentLifecycleState, TeamPreset, ThreadSummary } from '../../data/types';
import { getAgentColor } from '../../utils/agent-colors';
import { MarkdownEditor, getEditorTextarea } from './markdown-editor';

// ── Mock data for pickers ────────────────────────────────────────────────────

const MOCK_REPOS = [
  'wgergely/vaultspec-a2a',
  'wgergely/vaultspec-core',
  'wgergely/vaultspec-ui',
];

const MOCK_BRANCHES = [
  'main',
  'develop',
  'fix/auth-session',
  'feat/sqlmodel',
  'feat/rate-limit',
  'chore/cicd',
];

// ── Constants ────────────────────────────────────────────────────────────────

const MIN_INPUT_HEIGHT = 100;
const MAX_INPUT_HEIGHT = 480;

// ── Types ────────────────────────────────────────────────────────────────────

interface InputBarProps {
  agentState: AgentLifecycleState;
  onSend: (
    message: string,
    opts?: {
      preset?: TeamPreset;
      repo?: string;
      branch?: string;
      featureTag?: string;
    },
  ) => void;
  onStop?: () => void;
  teamPresets?: TeamPreset[];
  selectedPreset?: TeamPreset | null;
  onSelectPreset?: (preset: TeamPreset) => void;
  /** True when no thread exists yet or the thread has no events */
  isNewThread?: boolean;
  /** Existing threads for extracting feature tags */
  threads?: ThreadSummary[];
  /** The active thread (for read-only message mode) */
  activeThread?: ThreadSummary | null;
}

// ── Markdown shortcut helpers ────────────────────────────────────────────────

function wrapSelection(
  textarea: HTMLTextAreaElement,
  before: string,
  after: string,
  setMessage: (v: string) => void,
) {
  const { selectionStart, selectionEnd, value } = textarea;
  const selected = value.slice(selectionStart, selectionEnd);
  const replacement = `${before}${selected || 'text'}${after}`;
  const newValue =
    value.slice(0, selectionStart) + replacement + value.slice(selectionEnd);
  setMessage(newValue);

  requestAnimationFrame(() => {
    if (selected) {
      // Select the whole wrapped block
      textarea.setSelectionRange(selectionStart, selectionStart + replacement.length);
    } else {
      // Select placeholder "text"
      textarea.setSelectionRange(
        selectionStart + before.length,
        selectionStart + before.length + 4,
      );
    }
    textarea.focus();
  });
}

function insertLinePrefix(
  textarea: HTMLTextAreaElement,
  prefix: string,
  setMessage: (v: string) => void,
) {
  const { selectionStart, value } = textarea;
  // Find start of current line
  const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1;
  const newValue = value.slice(0, lineStart) + prefix + value.slice(lineStart);
  setMessage(newValue);

  requestAnimationFrame(() => {
    const newPos = selectionStart + prefix.length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
  });
}

// ── Component ────────────────────────────────────────────────────────────────

export function InputBar({
  agentState,
  onSend,
  onStop,
  teamPresets,
  selectedPreset,
  onSelectPreset,
  isNewThread,
  threads,
  activeThread,
  isDark,
}: InputBarProps & { isDark?: boolean }) {
  const [message, setMessage] = useState('');
  const [inputHeight, setInputHeight] = useState(MIN_INPUT_HEIGHT);
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);
  const userHasResized = useRef(false);
  const isWorking = agentState === 'working';
  const isInputRequired = agentState === 'input_required';
  const canSend = !isWorking && message.trim().length > 0;

  // Mode: "create" when no active thread, "message" when established
  const isCreateMode = !!isNewThread;

  // ── Auto-expansion logic ───────────────────────────────────────────────────
  const handleHeightChange = useCallback(
    (contentHeight: number) => {
      if (isResizing.current) return;

      // Calculate required height for the bar (content + widgets + padding)
      const padding = 64;
      const targetHeight = Math.max(
        MIN_INPUT_HEIGHT,
        Math.min(MAX_INPUT_HEIGHT, contentHeight + padding),
      );

      if (!userHasResized.current || message === '') {
        setInputHeight(targetHeight);
      }
    },
    [message],
  );

  // ── Create-mode local state ──────────────────────────────────────────────
  const [createRepo, setCreateRepo] = useState(MOCK_REPOS[0]);
  const [createBranch, setCreateBranch] = useState('');
  const [createFeatureTag, setCreateFeatureTag] = useState('');
  const [newBranchInput, setNewBranchInput] = useState('');
  const [newFeatureInput, setNewFeatureInput] = useState('');
  const [showNewBranch, setShowNewBranch] = useState(false);
  const [showNewFeature, setShowNewFeature] = useState(false);

  // Extract existing feature tags from threads
  const existingFeatureTags = useMemo(() => {
    if (!threads) return [];
    const tags = new Set<string>();
    threads.forEach((t) => {
      if (t.feature_tag) tags.add(t.feature_tag);
    });
    return Array.from(tags).sort();
  }, [threads]);

  // ── @ mention autocomplete ──────────────────────────────────────────────
  const [mentionState, setMentionState] = useState<{
    active: boolean;
    query: string;
    startPos: number;
    selectedIndex: number;
  }>({ active: false, query: '', startPos: 0, selectedIndex: 0 });

  const mentionPopupRef = useRef<HTMLDivElement>(null);

  const availableAgents = useMemo((): string[] => {
    // Agent names come from team status queries, not preset config
    return [];
  }, []);

  const filteredAgents = useMemo(() => {
    if (!mentionState.active) return [];
    const q = mentionState.query.toLowerCase();
    return availableAgents.filter((a) => a.toLowerCase().startsWith(q));
  }, [mentionState.active, mentionState.query, availableAgents]);

  const insertMention = useCallback(
    (agentName: string) => {
      const before = message.slice(0, mentionState.startPos);
      const after = message.slice(
        mentionState.startPos + mentionState.query.length + 1,
      );
      const newMessage = `${before}@${agentName} ${after}`;
      setMessage(newMessage);
      setMentionState({ active: false, query: '', startPos: 0, selectedIndex: 0 });

      requestAnimationFrame(() => {
        if (editorContainerRef.current) {
          const cursorPos = before.length + agentName.length + 2;
          const textarea = getEditorTextarea(editorContainerRef.current);
          if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(cursorPos, cursorPos);
          }
        }
      });
    },
    [message, mentionState.startPos, mentionState.query],
  );

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setMessage(val);

    const cursorPos = e.target.selectionStart ?? val.length;
    const textBeforeCursor = val.slice(0, cursorPos);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');

    if (lastAtIndex >= 0) {
      const charBefore = lastAtIndex > 0 ? textBeforeCursor[lastAtIndex - 1] : ' ';
      if (charBefore === ' ' || charBefore === '\n' || lastAtIndex === 0) {
        const query = textBeforeCursor.slice(lastAtIndex + 1);
        if (!query.includes(' ')) {
          setMentionState({
            active: true,
            query,
            startPos: lastAtIndex,
            selectedIndex: 0,
          });
          return;
        }
      }
    }

    setMentionState((prev) => (prev.active ? { ...prev, active: false } : prev));
  }, []);

  const handleSend = () => {
    if (!canSend) return;
    if (isCreateMode) {
      onSend(message.trim(), {
        preset: selectedPreset || undefined,
        repo: createRepo || undefined,
        branch: createBranch || undefined,
        featureTag: createFeatureTag || undefined,
      });
    } else {
      onSend(message.trim());
    }
    setMessage('');
    setInputHeight(MIN_INPUT_HEIGHT);
    userHasResized.current = false;
    setMentionState({ active: false, query: '', startPos: 0, selectedIndex: 0 });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mentionState.active && filteredAgents.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionState((prev) => ({
          ...prev,
          selectedIndex: (prev.selectedIndex + 1) % filteredAgents.length,
        }));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionState((prev) => ({
          ...prev,
          selectedIndex:
            (prev.selectedIndex - 1 + filteredAgents.length) % filteredAgents.length,
        }));
        return;
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault();
        insertMention(filteredAgents[mentionState.selectedIndex]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setMentionState({ active: false, query: '', startPos: 0, selectedIndex: 0 });
        return;
      }
    }

    const textarea = getEditorTextarea(editorContainerRef.current);

    if (textarea && (e.ctrlKey || e.metaKey)) {
      if (e.key === 'b') {
        e.preventDefault();
        wrapSelection(textarea, '**', '**', setMessage);
        return;
      }
      if (e.key === 'i') {
        e.preventDefault();
        wrapSelection(textarea, '_', '_', setMessage);
        return;
      }
      if (e.key === '`') {
        e.preventDefault();
        if (e.shiftKey) {
          wrapSelection(textarea, '```\n', '\n```', setMessage);
        } else {
          wrapSelection(textarea, '`', '`', setMessage);
        }
        return;
      }
      if (e.key === 'k') {
        e.preventDefault();
        const { selectionStart, selectionEnd, value } = textarea;
        const selected = value.slice(selectionStart, selectionEnd);
        const replacement = `[${selected || 'text'}](url)`;
        const newValue =
          value.slice(0, selectionStart) + replacement + value.slice(selectionEnd);
        setMessage(newValue);
        requestAnimationFrame(() => {
          if (selected) {
            const urlStart = selectionStart + selected.length + 3;
            textarea.setSelectionRange(urlStart, urlStart + 3);
          } else {
            textarea.setSelectionRange(selectionStart + 1, selectionStart + 5);
          }
          textarea.focus();
        });
        return;
      }
      if (e.shiftKey && e.key === '7') {
        e.preventDefault();
        insertLinePrefix(textarea, '1. ', setMessage);
        return;
      }
      if (e.shiftKey && e.key === '8') {
        e.preventDefault();
        insertLinePrefix(textarea, '- ', setMessage);
        return;
      }
    }

    if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      if (textarea) {
        const { selectionStart, selectionEnd, value } = textarea;
        const newValue =
          value.slice(0, selectionStart) + '  ' + value.slice(selectionEnd);
        setMessage(newValue);
        requestAnimationFrame(() => {
          textarea.setSelectionRange(selectionStart + 2, selectionStart + 2);
          textarea.focus();
        });
      }
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isResizing.current = true;
      userHasResized.current = true;
      const startY = e.clientY;
      const startHeight = inputHeight;

      const onMouseMove = (ev: MouseEvent) => {
        if (!isResizing.current) return;
        const newHeight = Math.max(
          MIN_INPUT_HEIGHT,
          Math.min(MAX_INPUT_HEIGHT, startHeight - (ev.clientY - startY)),
        );
        setInputHeight(newHeight);
      };

      const onMouseUp = () => {
        isResizing.current = false;
        globalThis.document.removeEventListener('mousemove', onMouseMove);
        globalThis.document.removeEventListener('mouseup', onMouseUp);
        globalThis.document.body.style.cursor = '';
        globalThis.document.body.style.userSelect = '';
      };

      globalThis.document.body.style.cursor = 'row-resize';
      globalThis.document.body.style.userSelect = 'none';
      globalThis.document.addEventListener('mousemove', onMouseMove);
      globalThis.document.addEventListener('mouseup', onMouseUp);
    },
    [inputHeight],
  );

  const borderColor = isInputRequired
    ? 'border-status-warning/50 ring-1 ring-status-warning/20'
    : 'border-border';

  const placeholder = isInputRequired
    ? 'Agent needs input...'
    : isWorking
      ? ''
      : isCreateMode
        ? 'Describe the task for your team...'
        : selectedPreset
          ? `Message ${selectedPreset.name}...`
          : 'Message team...';

  const displayRepo = isCreateMode ? createRepo : undefined;
  const displayBranch = isCreateMode ? createBranch : activeThread?.source_branch;
  const displayFeature = isCreateMode ? createFeatureTag : activeThread?.feature_tag;

  return (
    <div
      className={`relative border-t ${borderColor} bg-oxide-sidebar-bg shrink-0`}
      style={{ height: inputHeight }}
      data-focus-section="input-bar"
    >
      <div
        onMouseDown={handleResizeMouseDown}
        tabIndex={0}
        className="hover:bg-primary/30 active:bg-primary/50 absolute top-0 right-0 left-0 z-30 h-1.5 -translate-y-0.5 cursor-row-resize transition-colors"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize input area"
      />

      <div className="flex h-full flex-col px-4 pt-2 pb-2">
        <div className="flex h-8 shrink-0 items-center gap-1 overflow-x-auto">
          {teamPresets &&
            onSelectPreset &&
            (isCreateMode ? (
              <WidgetPicker
                icon={<Users className="text-oxide-icon h-3 w-3" />}
                value={selectedPreset?.name || 'Select team...'}
                items={teamPresets.map((p) => ({
                  id: p.id,
                  label: p.name,
                  description: p.description,
                  isSelected: selectedPreset?.id === p.id,
                  extra: p.worker_count ? (
                    <div className="mt-1 text-muted-foreground text-[0.5625rem]">
                      {p.worker_count} worker{p.worker_count !== 1 ? 's' : ''}
                    </div>
                  ) : undefined,
                }))}
                onSelect={(id) => {
                  const preset = teamPresets.find((p) => p.id === id);
                  if (preset) onSelectPreset(preset);
                }}
              />
            ) : (
              <WidgetReadOnly
                icon={<Users className="text-oxide-icon h-3 w-3" />}
                value={selectedPreset?.name || ''}
              />
            ))}

          {isCreateMode ? (
            <WidgetPicker
              icon={<FolderGit2 className="text-oxide-icon h-3 w-3" />}
              value={createRepo || 'Repository...'}
              items={MOCK_REPOS.map((r) => ({
                id: r,
                label: r,
                isSelected: createRepo === r,
              }))}
              onSelect={setCreateRepo}
            />
          ) : displayRepo ? (
            <WidgetReadOnly
              icon={<FolderGit2 className="text-oxide-icon h-3 w-3" />}
              value={displayRepo}
            />
          ) : null}

          {isCreateMode ? (
            <BranchPicker
              value={createBranch}
              branches={MOCK_BRANCHES}
              onSelect={setCreateBranch}
              newBranchInput={newBranchInput}
              onNewBranchInputChange={setNewBranchInput}
              showNewBranch={showNewBranch}
              onToggleNewBranch={setShowNewBranch}
            />
          ) : displayBranch ? (
            <WidgetReadOnly
              icon={<GitBranch className="text-oxide-icon h-3 w-3" />}
              value={displayBranch}
            />
          ) : null}

          {isCreateMode ? (
            <FeatureTagPicker
              value={createFeatureTag}
              existingTags={existingFeatureTags}
              onSelect={setCreateFeatureTag}
              newFeatureInput={newFeatureInput}
              onNewFeatureInputChange={setNewFeatureInput}
              showNewFeature={showNewFeature}
              onToggleNewFeature={setShowNewFeature}
            />
          ) : displayFeature ? (
            <WidgetReadOnly
              icon={<Tag className="text-oxide-icon h-3 w-3" />}
              value={`#${displayFeature}`}
            />
          ) : null}

          <div className="flex-1" />

          {isWorking && onStop && (
            <Button
              variant="terminal"
              size="sm"
              className="h-7 gap-1.5 px-3"
              onClick={onStop}
            >
              <Pause className="h-3 w-3" />
              Interrupt
            </Button>
          )}
        </div>

        <div className="relative mt-1 flex min-h-0 flex-1 items-end gap-2">
          {mentionState.active && filteredAgents.length > 0 && (
            <div
              ref={mentionPopupRef}
              role="listbox"
              aria-label="Mention agent"
              className="bg-popover border-border rounded-ui absolute bottom-full left-0 z-40 mb-1 w-56 overflow-hidden border shadow-xl"
            >
              <div className="py-1">
                <div className="px-3 py-1.5">
                  <span className="text-oxide-metadata text-[0.625rem] font-bold tracking-widest uppercase">
                    Mention agent
                  </span>
                </div>
                {filteredAgents.map((agent, idx) => {
                  const c = getAgentColor(agent);
                  const isSelected = idx === mentionState.selectedIndex;
                  return (
                    <button
                      key={agent}
                      role="option"
                      aria-selected={isSelected}
                      aria-label={`Mention ${agent}`}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        insertMention(agent);
                      }}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[0.75rem] transition-colors ${
                        isSelected ? 'bg-accent' : 'hover:bg-accent/50'
                      }`}
                    >
                      <span className={`h-2 w-2 rounded-full ${c.dot}`} />
                      <span className={`font-mono ${c.text}`}>{agent}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <MarkdownEditor
            ref={editorContainerRef}
            value={message}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onHeightChange={handleHeightChange}
            placeholder={placeholder}
            disabled={isWorking}
            isDark={isDark}
            className="bg-oxide-terminal-input rounded-terminal border-border/40 focus-within:border-primary/40 flex-1 border transition-colors"
            inputClassName={isInputRequired ? 'border-status-warning/50' : ''}
          />
          <Button
            size="icon"
            variant="default"
            className="rounded-control h-9 w-9 shrink-0"
            disabled={!canSend}
            onClick={handleSend}
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function WidgetReadOnly({ icon, value }: { icon: React.ReactNode; value: string }) {
  return (
    <div className="text-muted-foreground rounded-control bg-muted/30 flex h-7 shrink-0 cursor-default items-center gap-1.5 border border-transparent px-2 text-[0.6875rem] select-none">
      {icon}
      <span className="max-w-[10rem] truncate">{value}</span>
    </div>
  );
}

function WidgetPicker({
  icon,
  value,
  items,
  onSelect,
}: {
  icon: React.ReactNode;
  value: string;
  items: {
    id: string;
    label: string;
    description?: string;
    isSelected?: boolean;
    extra?: React.ReactNode;
  }[];
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors">
          {icon}
          <span className="max-w-[10rem] truncate">{value}</span>
          <ChevronDown className="h-2.5 w-2.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-1.5" align="start">
        <div className="space-y-0.5">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                onSelect(item.id);
                setOpen(false);
              }}
              aria-label={`Select ${item.label}`}
              className={`rounded-control hover:bg-accent flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors ${
                item.isSelected ? 'bg-accent' : ''
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[0.75rem]">{item.label}</span>
                  {item.isSelected && (
                    <Check className="text-primary h-3 w-3 shrink-0" />
                  )}
                </div>
                {item.description && (
                  <p className="text-muted-foreground mt-0.5 text-[0.625rem]">
                    {item.description}
                  </p>
                )}
                {item.extra}
              </div>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function BranchPicker({
  value,
  branches,
  onSelect,
  newBranchInput,
  onNewBranchInputChange,
  showNewBranch,
  onToggleNewBranch,
}: {
  value: string;
  branches: string[];
  onSelect: (branch: string) => void;
  newBranchInput: string;
  onNewBranchInputChange: (v: string) => void;
  showNewBranch: boolean;
  onToggleNewBranch: (v: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleCreateBranch = () => {
    const slug = newBranchInput
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9/._-]+/g, '-')
      .replace(/^-|-$/g, '');
    if (slug) {
      onSelect(slug);
      onNewBranchInputChange('');
      onToggleNewBranch(false);
      setOpen(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) onToggleNewBranch(false);
      }}
    >
      <PopoverTrigger asChild>
        <button className="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors">
          <GitBranch className="h-3 w-3" />
          <span className="max-w-[10rem] truncate">{value || 'Branch...'}</span>
          <ChevronDown className="h-2.5 w-2.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-1.5" align="start">
        <div className="max-h-[16rem] space-y-0.5 overflow-y-auto">
          {branches.map((b) => (
            <button
              key={b}
              onClick={() => {
                onSelect(b);
                setOpen(false);
              }}
              className={`rounded-control hover:bg-accent flex w-full items-center gap-2 px-2.5 py-1.5 text-left font-mono text-[0.75rem] transition-colors ${
                value === b ? 'bg-accent' : ''
              }`}
            >
              <GitBranch className="text-muted-foreground h-3 w-3 shrink-0" />
              <span className="flex-1 truncate">{b}</span>
              {value === b && <Check className="text-primary h-3 w-3 shrink-0" />}
            </button>
          ))}
        </div>
        <div className="border-border mt-1 border-t pt-1">
          {showNewBranch ? (
            <div className="flex items-center gap-1.5 px-1">
              <Input
                ref={inputRef}
                value={newBranchInput}
                onChange={(e) => onNewBranchInputChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateBranch();
                  if (e.key === 'Escape') onToggleNewBranch(false);
                }}
                placeholder="feat/my-branch"
                autoFocus
                className="h-7 flex-1 px-2 font-mono text-[0.6875rem]"
              />
              <Button
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={handleCreateBranch}
                disabled={!newBranchInput.trim()}
              >
                <Check className="h-3 w-3" />
              </Button>
            </div>
          ) : (
            <button
              onClick={() => {
                onToggleNewBranch(true);
              }}
              className="rounded-control hover:bg-accent text-muted-foreground flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors"
            >
              <Plus className="h-3 w-3" />
              <span>New branch</span>
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function FeatureTagPicker({
  value,
  existingTags,
  onSelect,
  newFeatureInput,
  onNewFeatureInputChange,
  showNewFeature,
  onToggleNewFeature,
}: {
  value: string;
  existingTags: string[];
  onSelect: (tag: string) => void;
  newFeatureInput: string;
  onNewFeatureInputChange: (v: string) => void;
  showNewFeature: boolean;
  onToggleNewFeature: (v: boolean) => void;
}) {
  const [open, setOpen] = useState(false);

  const handleCreateFeature = () => {
    const slug = newFeatureInput
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, '-')
      .replace(/^-|-$/g, '');
    if (slug) {
      onSelect(slug);
      onNewFeatureInputChange('');
      onToggleNewFeature(false);
      setOpen(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) onToggleNewFeature(false);
      }}
    >
      <PopoverTrigger asChild>
        <button className="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors">
          <Tag className="h-3 w-3" />
          <span className="max-w-[10rem] truncate">
            {value ? `#${value}` : 'Feature...'}
          </span>
          <ChevronDown className="h-2.5 w-2.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-1.5" align="start">
        <div className="max-h-[16rem] space-y-0.5 overflow-y-auto">
          {existingTags.length === 0 && !showNewFeature && (
            <div className="text-muted-foreground px-2.5 py-2 text-[0.6875rem] italic">
              No existing features
            </div>
          )}
          {existingTags.map((tag) => (
            <button
              key={tag}
              onClick={() => {
                onSelect(tag);
                setOpen(false);
              }}
              className={`rounded-control hover:bg-accent flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors ${
                value === tag ? 'bg-accent' : ''
              }`}
            >
              <Tag className="text-muted-foreground h-3 w-3 shrink-0" />
              <span className="flex-1 truncate">#{tag}</span>
              {value === tag && <Check className="text-primary h-3 w-3 shrink-0" />}
            </button>
          ))}
        </div>
        <div className="border-border mt-1 border-t pt-1">
          {showNewFeature ? (
            <div className="flex items-center gap-1.5 px-1">
              <Input
                value={newFeatureInput}
                onChange={(e) => onNewFeatureInputChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateFeature();
                  if (e.key === 'Escape') onToggleNewFeature(false);
                }}
                placeholder="my-feature"
                autoFocus
                className="h-7 flex-1 px-2 font-mono text-[0.6875rem]"
              />
              <Button
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={handleCreateFeature}
                disabled={!newFeatureInput.trim()}
              >
                <Check className="h-3 w-3" />
              </Button>
            </div>
          ) : (
            <button
              onClick={() => onToggleNewFeature(true)}
              className="rounded-control hover:bg-accent text-muted-foreground flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors"
            >
              <Plus className="h-3 w-3" />
              <span>New feature</span>
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
