---
date: 2026-03-01
type: research
feature: figma-make-resources
description: 'Catalog of Figma Make resources, templates, and reference implementations.'
---

# Figma Make Resource Catalog

**Date**: 2026-03-01
**Make Project**: VaultSpec A2A Gateway
**File Key**: `EAs7Eh1lxKVzBqzke5HASU`
**URL**:
`https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface`

---

## Source Files

Full list of MCP resources available via
`file://figma/make/source/EAs7Eh1lxKVzBqzke5HASU/{path}`.

### Entry Point

| Make Path         | Local Equivalent         |
| ----------------- | ------------------------ |
| `src/app/App.tsx` | `src/ui/src/app/App.tsx` |

### Layout Components

| Make Path                                        | Local Path                                              | Status                 |
| ------------------------------------------------ | ------------------------------------------------------- | ---------------------- |
| `src/app/components/layout/app-shell.tsx`        | `src/ui/src/app/components/layout/app-shell.tsx`        | Adapted (live WS/REST) |
| `src/app/components/layout/sidebar.tsx`          | `src/ui/src/app/components/layout/sidebar.tsx`          | Adapted                |
| `src/app/components/layout/tab-bar.tsx`          | `src/ui/src/app/components/layout/tab-bar.tsx`          | Adapted                |
| `src/app/components/layout/status-bar.tsx`       | `src/ui/src/app/components/layout/status-bar.tsx`       | Adapted                |
| `src/app/components/layout/state-indicators.tsx` | `src/ui/src/app/components/layout/state-indicators.tsx` | Adapted                |

### Stream Components

| Make Path                                        | Local Path                                              | Status                |
| ------------------------------------------------ | ------------------------------------------------------- | --------------------- |
| `src/app/components/stream/message-stream.tsx`   | `src/ui/src/app/components/stream/message-stream.tsx`   | Adapted               |
| `src/app/components/stream/message-bubble.tsx`   | `src/ui/src/app/components/stream/message-bubble.tsx`   | Adapted               |
| `src/app/components/stream/thought-block.tsx`    | `src/ui/src/app/components/stream/thought-block.tsx`    | Adapted               |
| `src/app/components/stream/tool-call-card.tsx`   | `src/ui/src/app/components/stream/tool-call-card.tsx`   | Adapted               |
| `src/app/components/stream/artifact-card.tsx`    | `src/ui/src/app/components/stream/artifact-card.tsx`    | Adapted               |
| `src/app/components/stream/plan-update-card.tsx` | `src/ui/src/app/components/stream/plan-update-card.tsx` | Adapted               |
| `src/app/components/stream/error-alert.tsx`      | `src/ui/src/app/components/stream/error-alert.tsx`      | Adapted               |
| `src/app/components/stream/input-bar.tsx`        | `src/ui/src/app/components/stream/input-bar.tsx`        | Adapted               |
| `src/app/components/stream/markdown-editor.tsx`  | `src/ui/src/app/components/stream/markdown-editor.tsx`  | Adapted               |
| `src/app/components/stream/permission-card.tsx`  | _(absorbed into permission-modal)_                      | Not ported separately |

### Inspector Components

| Make Path                                          | Local Path                                                | Status  |
| -------------------------------------------------- | --------------------------------------------------------- | ------- |
| `src/app/components/inspector/inspector-panel.tsx` | `src/ui/src/app/components/inspector/inspector-panel.tsx` | Adapted |

### Permission Components

| Make Path                                            | Local Path                                                  | Status  |
| ---------------------------------------------------- | ----------------------------------------------------------- | ------- |
| `src/app/components/permission/permission-modal.tsx` | `src/ui/src/app/components/permission/permission-modal.tsx` | Adapted |

### Figma Utility Components

| Make Path                                        | Local Path                                              | Status       |
| ------------------------------------------------ | ------------------------------------------------------- | ------------ |
| `src/app/components/figma/ImageWithFallback.tsx` | `src/ui/src/app/components/figma/ImageWithFallback.tsx` | Copied as-is |

### UI Primitives (shadcn/ui)

All 47 primitives are available in Make and copied/adapted to the local project.

| Make Path                                      | Local Path                                            | Status     |
| ---------------------------------------------- | ----------------------------------------------------- | ---------- |
| `src/app/components/ui/accordion.tsx`          | `src/ui/src/app/components/ui/accordion.tsx`          | Copied     |
| `src/app/components/ui/alert-dialog.tsx`       | `src/ui/src/app/components/ui/alert-dialog.tsx`       | Copied     |
| `src/app/components/ui/alert.tsx`              | `src/ui/src/app/components/ui/alert.tsx`              | Copied     |
| `src/app/components/ui/aspect-ratio.tsx`       | `src/ui/src/app/components/ui/aspect-ratio.tsx`       | Copied     |
| `src/app/components/ui/avatar.tsx`             | `src/ui/src/app/components/ui/avatar.tsx`             | Copied     |
| `src/app/components/ui/badge.tsx`              | `src/ui/src/app/components/ui/badge.tsx`              | Copied     |
| `src/app/components/ui/breadcrumb.tsx`         | `src/ui/src/app/components/ui/breadcrumb.tsx`         | Copied     |
| `src/app/components/ui/button.tsx`             | `src/ui/src/app/components/ui/button.tsx`             | Copied     |
| `src/app/components/ui/calendar.tsx`           | `src/ui/src/app/components/ui/calendar.tsx`           | Copied     |
| `src/app/components/ui/card.tsx`               | `src/ui/src/app/components/ui/card.tsx`               | Copied     |
| `src/app/components/ui/carousel.tsx`           | `src/ui/src/app/components/ui/carousel.tsx`           | Copied     |
| `src/app/components/ui/checkbox.tsx`           | `src/ui/src/app/components/ui/checkbox.tsx`           | Copied     |
| `src/app/components/ui/collapsible.tsx`        | `src/ui/src/app/components/ui/collapsible.tsx`        | Copied     |
| `src/app/components/ui/command.tsx`            | `src/ui/src/app/components/ui/command.tsx`            | Copied     |
| `src/app/components/ui/context-menu.tsx`       | `src/ui/src/app/components/ui/context-menu.tsx`       | Copied     |
| `src/app/components/ui/dialog.tsx`             | `src/ui/src/app/components/ui/dialog.tsx`             | Copied     |
| `src/app/components/ui/drawer.tsx`             | `src/ui/src/app/components/ui/drawer.tsx`             | Copied     |
| `src/app/components/ui/dropdown-menu.tsx`      | `src/ui/src/app/components/ui/dropdown-menu.tsx`      | Copied     |
| `src/app/components/ui/form.tsx`               | `src/ui/src/app/components/ui/form.tsx`               | Copied     |
| `src/app/components/ui/hover-card.tsx`         | `src/ui/src/app/components/ui/hover-card.tsx`         | Copied     |
| `src/app/components/ui/input-otp.tsx`          | `src/ui/src/app/components/ui/input-otp.tsx`          | Copied     |
| `src/app/components/ui/input.tsx`              | `src/ui/src/app/components/ui/input.tsx`              | Copied     |
| `src/app/components/ui/label.tsx`              | `src/ui/src/app/components/ui/label.tsx`              | Copied     |
| `src/app/components/ui/menubar.tsx`            | `src/ui/src/app/components/ui/menubar.tsx`            | Copied     |
| `src/app/components/ui/navigation-menu.tsx`    | `src/ui/src/app/components/ui/navigation-menu.tsx`    | Copied     |
| `src/app/components/ui/notification-pills.tsx` | `src/ui/src/app/components/ui/notification-pills.tsx` | Copied     |
| `src/app/components/ui/pagination.tsx`         | `src/ui/src/app/components/ui/pagination.tsx`         | Copied     |
| `src/app/components/ui/popover.tsx`            | `src/ui/src/app/components/ui/popover.tsx`            | Copied     |
| `src/app/components/ui/progress.tsx`           | `src/ui/src/app/components/ui/progress.tsx`           | Copied     |
| `src/app/components/ui/radio-group.tsx`        | `src/ui/src/app/components/ui/radio-group.tsx`        | Copied     |
| `src/app/components/ui/resizable.tsx`          | `src/ui/src/app/components/ui/resizable.tsx`          | Copied     |
| `src/app/components/ui/scroll-area.tsx`        | `src/ui/src/app/components/ui/scroll-area.tsx`        | Copied     |
| `src/app/components/ui/select.tsx`             | `src/ui/src/app/components/ui/select.tsx`             | Copied     |
| `src/app/components/ui/separator.tsx`          | `src/ui/src/app/components/ui/separator.tsx`          | Copied     |
| `src/app/components/ui/sheet.tsx`              | `src/ui/src/app/components/ui/sheet.tsx`              | Copied     |
| `src/app/components/ui/sidebar.tsx`            | `src/ui/src/app/components/ui/sidebar.tsx`            | Copied     |
| `src/app/components/ui/skeleton.tsx`           | `src/ui/src/app/components/ui/skeleton.tsx`           | Copied     |
| `src/app/components/ui/slider.tsx`             | `src/ui/src/app/components/ui/slider.tsx`             | Copied     |
| `src/app/components/ui/switch.tsx`             | `src/ui/src/app/components/ui/switch.tsx`             | Copied     |
| `src/app/components/ui/table.tsx`              | `src/ui/src/app/components/ui/table.tsx`              | Copied     |
| `src/app/components/ui/tabs.tsx`               | `src/ui/src/app/components/ui/tabs.tsx`               | Copied     |
| `src/app/components/ui/textarea.tsx`           | `src/ui/src/app/components/ui/textarea.tsx`           | Copied     |
| `src/app/components/ui/toggle-group.tsx`       | `src/ui/src/app/components/ui/toggle-group.tsx`       | Copied     |
| `src/app/components/ui/toggle.tsx`             | `src/ui/src/app/components/ui/toggle.tsx`             | Copied     |
| `src/app/components/ui/tooltip.tsx`            | `src/ui/src/app/components/ui/tooltip.tsx`            | Copied     |
| `src/app/components/ui/use-mobile.ts`          | `src/ui/src/app/components/ui/use-mobile.ts`          | Copied     |
| `src/app/components/ui/utils.ts`               | `src/ui/src/app/components/ui/utils.ts`               | Copied     |
| `src/app/components/ui/sonner.tsx`             | _(removed — next-themes dep)_                         | Not ported |
| `src/app/components/ui/chart.tsx`              | _(removed — recharts dep)_                            | Not ported |

### Data / Hooks / Utils

| Make Path                            | Local Path                                  | Notes                                                      |
| ------------------------------------ | ------------------------------------------- | ---------------------------------------------------------- |
| `src/app/data/types.ts`              | `src/ui/src/app/data/types.ts`              | Adapted (Wire\* prefix types removed, frontend types only) |
| `src/app/data/mock-data.ts`          | _(deleted)_                                 | Replaced by live REST/WS                                   |
| `src/app/hooks/use-app-state.ts`     | _(replaced)_                                | Decomposed into Zustand store + TanStack Query             |
| `src/app/hooks/use-keyboard-nav.ts`  | `src/ui/src/app/hooks/use-keyboard-nav.ts`  | Copied                                                     |
| `src/app/hooks/use-notifications.ts` | `src/ui/src/app/hooks/use-notifications.ts` | Adapted                                                    |
| `src/app/utils/agent-colors.ts`      | `src/ui/src/app/utils/agent-colors.ts`      | Copied                                                     |
| `src/app/utils/palette.ts`           | `src/ui/src/app/utils/palette.ts`           | Copied                                                     |
| `src/app/utils/logger.ts`            | `src/ui/src/app/utils/logger.ts`            | Copied                                                     |

### Styles

| Make Path                 | Local Path                       | Status                       |
| ------------------------- | -------------------------------- | ---------------------------- |
| `src/styles/theme.css`    | `src/ui/src/styles/theme.css`    | Copied (OKLCH design tokens) |
| `src/styles/tailwind.css` | `src/ui/src/styles/tailwind.css` | Copied                       |
| `src/styles/index.css`    | `src/ui/src/styles/index.css`    | Copied                       |
| `src/styles/fonts.css`    | `src/ui/src/styles/fonts.css`    | Copied                       |

### Config Files

| Make Path            | Local Path                  | Status                                     |
| -------------------- | --------------------------- | ------------------------------------------ |
| `package.json`       | `src/ui/package.json`       | Adapted (live deps, no mock-only packages) |
| `vite.config.ts`     | `src/ui/vite.config.ts`     | Adapted                                    |
| `postcss.config.mjs` | `src/ui/postcss.config.mjs` | Copied                                     |

---

## Local-Only Files (not in Make)

Files added during the backend integration phase that have no Make equivalent:

| Local Path                                 | Purpose                                                      |
| ------------------------------------------ | ------------------------------------------------------------ |
| `src/ui/src/app/api/rest-client.ts`        | 8 typed REST endpoints                                       |
| `src/ui/src/app/api/websocket-client.ts`   | WS client (reconnect, heartbeat, sequence dedup)             |
| `src/ui/src/app/api/wire-types.ts`         | Wire types with`Wire*`prefix (WireThreadSummary, etc.)       |
| `src/ui/src/app/api/mappers.ts`            | Wire → frontend type translation                             |
| `src/ui/src/app/store/app-store.ts`        | Zustand v5 vanilla store (5 slices)                          |
| `src/ui/src/app/bridge/ws-bridge.ts`       | WS event → Zustand + TanStack Query dispatch                 |
| `src/ui/src/app/queries/`                  | TanStack Query hooks (threads, team, snapshots, permissions) |
| `src/ui/figma.config.json`                 | Code Connect CLI config                                      |
| `src/ui/src/app/components/**/*.figma.tsx` | 27 Code Connect mapping files                                |

---

## Code Connect Status

All 28 component mappings (27 files) are defined and parse cleanly:

```bash
npx figma connect publish --dry-run --config figma.config.json
→ 28 components detected, 0 warnings
```yaml

**Publish blocker**: `FIGMA_ACCESS_TOKEN`needs "Code Connect: Write" scope.
Regenerate at figma.com/settings, then run`npm run figma:publish`in`src/ui/`.

**Make URL limitation**: Code Connect CLI cannot validate `figma.com/make/`URLs
(only`figma.com/design/`Design files).`--skip-validation` is included in the
`figma:publish` script to bypass this.
