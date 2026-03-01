/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * VaultSpec Palette — Centralized color system
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * All colors in the app derive from this single module.
 *
 * ACCENTS:    8 perceptually-uniform hues at equal lightness & low chroma.
 *             Used for agent identity, document types, model providers, etc.
 *             Assigned dynamically via hash — never hardcoded per-agent.
 *
 * STATUS:     4 semantic colors (success, warning, error, info).
 *             Used for connection state, tool results, thread lifecycle.
 *
 * UI ROLES:   Named mappings from accent indices to UI purposes.
 *             Change these to re-theme toolbar, inspector, etc. without
 *             touching component code.
 *
 * CSS VARS:   This module defines the OKLCH values consumed by theme.css as:
 *             --accent-0 … --accent-7
 *             --status-success, --status-warning, --status-error, --status-info
 *
 * TAILWIND:   theme.css registers --color-accent-0 etc. in @theme inline,
 *             giving you classes like:
 *               text-accent-0   bg-accent-3/20   border-accent-5/40
 *               text-status-success   bg-status-error/15
 *
 * SWITCHING:  To change palettes, swap the `ACTIVE_PALETTE` export below.
 *             The rest of the app adapts automatically.
 * ═══════════════════════════════════════════════════════════════════════════════
 */

// ── Palette definitions ─────────────────────────────────────────────────────────

export interface AccentDef {
  name: string;
  hue: number;
  dark: string; // oklch() for .dark
  light: string; // oklch() for :root
}

export interface StatusDef {
  dark: string;
  light: string;
}

export interface PaletteDef {
  id: string;
  label: string;
  accents: AccentDef[];
  status: {
    success: StatusDef;
    warning: StatusDef;
    error: StatusDef;
    info: StatusDef;
  };
}

// ── A: Oxide — Cool mineral tones ───────────────────────────────────────────────
// Muted, desaturated, perceptually even. L≈0.72/C≈0.06 (dark), L≈0.48/C≈0.08 (light)

const OXIDE: PaletteDef = {
  id: 'oxide',
  label: 'Oxide',
  accents: [
    {
      name: 'slate',
      hue: 240,
      dark: 'oklch(0.72 0.06 240)',
      light: 'oklch(0.48 0.08 240)',
    },
    {
      name: 'sage',
      hue: 155,
      dark: 'oklch(0.72 0.06 155)',
      light: 'oklch(0.48 0.08 155)',
    },
    {
      name: 'mauve',
      hue: 310,
      dark: 'oklch(0.72 0.06 310)',
      light: 'oklch(0.48 0.08 310)',
    },
    {
      name: 'sand',
      hue: 75,
      dark: 'oklch(0.74 0.06 75)',
      light: 'oklch(0.46 0.08 75)',
    },
    {
      name: 'copper',
      hue: 45,
      dark: 'oklch(0.72 0.07 45)',
      light: 'oklch(0.48 0.09 45)',
    },
    {
      name: 'teal',
      hue: 195,
      dark: 'oklch(0.72 0.06 195)',
      light: 'oklch(0.48 0.08 195)',
    },
    {
      name: 'lavender',
      hue: 280,
      dark: 'oklch(0.72 0.06 280)',
      light: 'oklch(0.48 0.08 280)',
    },
    {
      name: 'rose',
      hue: 355,
      dark: 'oklch(0.72 0.06 355)',
      light: 'oklch(0.48 0.08 355)',
    },
  ],
  status: {
    success: { dark: 'oklch(0.72 0.12 155)', light: 'oklch(0.45 0.14 155)' },
    warning: { dark: 'oklch(0.78 0.12 85)', light: 'oklch(0.52 0.14 85)' },
    error: { dark: 'oklch(0.68 0.14 25)', light: 'oklch(0.50 0.16 25)' },
    info: { dark: 'oklch(0.72 0.10 240)', light: 'oklch(0.48 0.12 240)' },
  },
};

// ── B: Patina — Warm oxidized tones ─────────────────────────────────────────────
// Shifted warmer, slightly higher chroma for organic warmth.

const PATINA: PaletteDef = {
  id: 'patina',
  label: 'Patina',
  accents: [
    {
      name: 'bronze',
      hue: 55,
      dark: 'oklch(0.72 0.07 55)',
      light: 'oklch(0.48 0.09 55)',
    },
    {
      name: 'verdigris',
      hue: 170,
      dark: 'oklch(0.72 0.07 170)',
      light: 'oklch(0.48 0.09 170)',
    },
    {
      name: 'plum',
      hue: 320,
      dark: 'oklch(0.72 0.07 320)',
      light: 'oklch(0.48 0.09 320)',
    },
    {
      name: 'ochre',
      hue: 80,
      dark: 'oklch(0.74 0.07 80)',
      light: 'oklch(0.46 0.09 80)',
    },
    {
      name: 'terracotta',
      hue: 30,
      dark: 'oklch(0.72 0.08 30)',
      light: 'oklch(0.48 0.10 30)',
    },
    {
      name: 'celadon',
      hue: 150,
      dark: 'oklch(0.72 0.06 150)',
      light: 'oklch(0.48 0.08 150)',
    },
    {
      name: 'wisteria',
      hue: 290,
      dark: 'oklch(0.72 0.07 290)',
      light: 'oklch(0.48 0.09 290)',
    },
    {
      name: 'clay',
      hue: 15,
      dark: 'oklch(0.72 0.07 15)',
      light: 'oklch(0.48 0.09 15)',
    },
  ],
  status: {
    success: { dark: 'oklch(0.72 0.12 160)', light: 'oklch(0.45 0.14 160)' },
    warning: { dark: 'oklch(0.78 0.12 80)', light: 'oklch(0.52 0.14 80)' },
    error: { dark: 'oklch(0.68 0.14 20)', light: 'oklch(0.50 0.16 20)' },
    info: { dark: 'oklch(0.72 0.10 230)', light: 'oklch(0.48 0.12 230)' },
  },
};

// ── C: Phosphor — Terminal glow, higher contrast ────────────────────────────────
// Slightly more vivid (C≈0.10), CRT-inspired but modern.

const PHOSPHOR: PaletteDef = {
  id: 'phosphor',
  label: 'Phosphor',
  accents: [
    {
      name: 'cobalt',
      hue: 245,
      dark: 'oklch(0.72 0.10 245)',
      light: 'oklch(0.48 0.12 245)',
    },
    {
      name: 'emerald',
      hue: 155,
      dark: 'oklch(0.72 0.10 155)',
      light: 'oklch(0.48 0.12 155)',
    },
    {
      name: 'violet',
      hue: 300,
      dark: 'oklch(0.72 0.10 300)',
      light: 'oklch(0.48 0.12 300)',
    },
    {
      name: 'amber',
      hue: 80,
      dark: 'oklch(0.74 0.10 80)',
      light: 'oklch(0.46 0.12 80)',
    },
    {
      name: 'flame',
      hue: 35,
      dark: 'oklch(0.72 0.11 35)',
      light: 'oklch(0.48 0.13 35)',
    },
    {
      name: 'cyan',
      hue: 195,
      dark: 'oklch(0.72 0.10 195)',
      light: 'oklch(0.48 0.12 195)',
    },
    {
      name: 'iris',
      hue: 275,
      dark: 'oklch(0.72 0.10 275)',
      light: 'oklch(0.48 0.12 275)',
    },
    {
      name: 'coral',
      hue: 10,
      dark: 'oklch(0.72 0.10 10)',
      light: 'oklch(0.48 0.12 10)',
    },
  ],
  status: {
    success: { dark: 'oklch(0.72 0.14 155)', light: 'oklch(0.45 0.16 155)' },
    warning: { dark: 'oklch(0.78 0.14 85)', light: 'oklch(0.52 0.16 85)' },
    error: { dark: 'oklch(0.68 0.16 25)', light: 'oklch(0.50 0.18 25)' },
    info: { dark: 'oklch(0.72 0.12 240)', light: 'oklch(0.48 0.14 240)' },
  },
};

// ── Active palette ──────────────────────────────────────────────────────────────
// Change this single line to switch the entire app's color personality.

export const PALETTES = { oxide: OXIDE, patina: PATINA, phosphor: PHOSPHOR } as const;
export type PaletteId = keyof typeof PALETTES;
export const ACTIVE_PALETTE: PaletteDef = OXIDE;

// ── Accent count ────────────────────────────────────────────────────────────────

export const ACCENT_COUNT = 8;

// ── Tailwind safelist ───────────────────────────────────────────────────────────
// Tailwind's JIT scanner can't detect dynamically-constructed class names like
// `text-accent-${i}`. This block ensures all palette utility classes are
// included in the build output. DO NOT DELETE.
// prettier-ignore
export const _PALETTE_SAFELIST = [
  'text-accent-0', 'text-accent-1', 'text-accent-2', 'text-accent-3',
  'text-accent-4', 'text-accent-5', 'text-accent-6', 'text-accent-7',
  'bg-accent-0', 'bg-accent-1', 'bg-accent-2', 'bg-accent-3',
  'bg-accent-4', 'bg-accent-5', 'bg-accent-6', 'bg-accent-7',
  'bg-accent-0/15', 'bg-accent-1/15', 'bg-accent-2/15', 'bg-accent-3/15',
  'bg-accent-4/15', 'bg-accent-5/15', 'bg-accent-6/15', 'bg-accent-7/15',
  'border-accent-0/30', 'border-accent-1/30', 'border-accent-2/30', 'border-accent-3/30',
  'border-accent-4/30', 'border-accent-5/30', 'border-accent-6/30', 'border-accent-7/30',
  'ring-accent-0/30', 'ring-accent-1/30', 'ring-accent-2/30', 'ring-accent-3/30',
  'ring-accent-4/30', 'ring-accent-5/30', 'ring-accent-6/30', 'ring-accent-7/30',
  'text-status-success', 'text-status-warning', 'text-status-error', 'text-status-info',
  'bg-status-success', 'bg-status-warning', 'bg-status-error', 'bg-status-info',
  'bg-status-success/5', 'bg-status-warning/5', 'bg-status-error/5', 'bg-status-info/5',
  'bg-status-success/15', 'bg-status-warning/15', 'bg-status-error/15', 'bg-status-info/15',
  'border-status-success/30', 'border-status-warning/30', 'border-status-error/30', 'border-status-info/30',
  'border-status-warning/50', 'ring-status-warning/20',
] as const;

// ── UI role mappings ────────────────────────────────────────────────────────────
// Map semantic UI roles → accent indices. Components reference these instead
// of hardcoding accent-0, accent-3, etc.

export const UI = {
  /** Plans toolbar button, document header icon, file badges */
  plans: 0, // slate
  /** Members dropdown active state */
  members: 1, // sage
  /** Search popover active state */
  search: 6, // lavender
  /** Hyperlinks */
  link: 0, // slate
  /** Artifact file icons */
  artifact: 0, // slate
  /** Plan update icons */
  plan: 6, // lavender
  /** URL document type */
  url: 1, // sage
  /** API document type */
  api: 3, // sand
  /** Note / default document type */
  note: 2, // mauve
  /** Copy-success feedback */
  copySuccess: 1, // sage
  /** Input required border highlight */
  inputRequired: 'warning' as const,
} as const;

// ── Utility: accent class builders ──────────────────────────────────────────────
// Returns Tailwind class strings using the accent-N custom color utilities.

export function accentClasses(index: number) {
  const i = index % ACCENT_COUNT;
  return {
    text: `text-accent-${i}`,
    bg: `bg-accent-${i}/15`,
    bgSolid: `bg-accent-${i}`,
    border: `border-accent-${i}/30`,
    dot: `bg-accent-${i}`,
    badge: `bg-accent-${i}/15 text-accent-${i} border-accent-${i}/30`,
    ring: `ring-accent-${i}/30`,
  };
}

export function statusClasses(status: 'success' | 'warning' | 'error' | 'info') {
  return {
    text: `text-status-${status}`,
    bg: `bg-status-${status}/15`,
    bgSolid: `bg-status-${status}`,
    border: `border-status-${status}/30`,
    dot: `bg-status-${status}`,
  };
}

/** Tailwind classes for a UI role accent */
export function uiAccent(role: keyof typeof UI) {
  const mapping = UI[role];
  if (typeof mapping === 'string') {
    // It's a status key
    return statusClasses(mapping);
  }
  return accentClasses(mapping);
}

// ── djb2 hash → index ──────────────────────────────────────────────────────────

function djb2(str: string): number {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) ^ str.charCodeAt(i);
  }
  return hash >>> 0; // unsigned
}

/**
 * Deterministic hash of a string to an accent index.
 * Same string always maps to the same color.
 */
export function hashToAccentIndex(name: string): number {
  if (!name) return 0;
  return djb2(name) % ACCENT_COUNT;
}
