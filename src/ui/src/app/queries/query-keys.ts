/**
 * Typed cache key factory.
 *
 * Using functions returning `as const` tuples ensures TanStack Query
 * can match / invalidate keys without string comparisons.
 */

export const queryKeys = {
  threads: {
    list: () => ['threads', 'list'] as const,
    state: (id: string) => ['threads', id, 'state'] as const,
    metadata: (id: string) => ['threads', id, 'metadata'] as const,
  },
  team: {
    status: () => ['team', 'status'] as const,
    presets: () => ['team', 'presets'] as const,
  },
} as const;
