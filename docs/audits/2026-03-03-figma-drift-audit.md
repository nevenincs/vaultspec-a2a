---
title: "Figma Code Connect Audit"
source: "Figma Make (mcp_figma_get_metadata, get_design_context, read_resource)"
relevance: 10
description: "Audit checking for drifts between the Figma Make master UI generation and the local `.figma.tsx` synced React UI codebase."
---

## Figma Drift Audit

**Date:** 2026-03-03
**Target:** `src/ui/src/app/*` -> `figma://make/source/EAs7Eh1lxKVzBqzke5HASU/src/app/*`

## Executive Summary

A comprehensive audit of the local React UI codebase was conducted against the generative output from the VaultSpec-A2A-Control-Surface Figma Make prototype.

The codebase incorporates Code Connect bindings mapping to the Figma AI instances. After fully re-initializing the Figma MCP (resolving the `/mcp` vs SSE handshake), we inspected the internal document AST directly.

## Findings

1. **Structural Parity:** There is **zero functional or visual layout drift** between the Figma source and the local repository.
2. **State Management Migration:** The codebase actively maintains a superior state layer (TanStack queries + Zustand). The raw Figma output relies on outdated local hooks (`useAppState`) and static mock injections. The current React integration successfully preserves the Figma aesthetics while applying the necessary programmatic overrides.
3. **Cosmetic Source Variances:** The only textual drifts discovered inside the React components (`tool-call-card.tsx`, `sidebar.tsx`, etc.) are direct results of the local `prettier-plugin-tailwindcss` reorganizing class ordering by specificity. This is expected and strictly compliant.

## Conclusion

The frontend UI is thoroughly synchronized with the current state of the Figma design. No codebase updates are required to patch visual drifts. It is safe to proceed to backend evaluation once the Svelte ecosystem purge is fully validated.
