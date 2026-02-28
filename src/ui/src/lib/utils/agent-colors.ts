/**
 * Agent color assignment — deterministic, palette-driven.
 *
 * Uses djb2 hash of agent name → accent index from the centralized palette.
 * All accent classes reference CSS custom properties (--accent-0 … --accent-7)
 * defined in app.css, which derive from palette.ts.
 *
 * Usage:
 *   const color = getAgentColor('Planner');
 *   <span class={color.text}>Planner</span>
 *   <div class={`border ${color.border}`}>…</div>
 */

import { hashToAccentIndex, accentClasses } from './palette';

export type AgentColorSet = {
  /** e.g. "text-accent-3" */
  text: string;
  /** e.g. "bg-accent-3/15" */
  bg: string;
  /** e.g. "bg-accent-3" (solid) */
  bgSolid: string;
  /** e.g. "border-accent-3/30" */
  border: string;
  /** e.g. "bg-accent-3" (for dots/strips) */
  dot: string;
  /** Combined badge: bg + text + border */
  badge: string;
  /** e.g. "ring-accent-3/30" */
  ring: string;
  /** The accent index (0-7) for programmatic use */
  index: number;
};

/**
 * Get a deterministic color set for an agent by name.
 * Same name → same color, every time.
 */
export function getAgentColor(agentName: string): AgentColorSet {
  const index = hashToAccentIndex(agentName);
  return {
    ...accentClasses(index),
    index,
  };
}
