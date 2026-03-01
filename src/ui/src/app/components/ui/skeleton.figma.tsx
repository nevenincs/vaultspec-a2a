import figma from '@figma/code-connect'
import { Skeleton } from './skeleton'

/**
 * Code Connect mapping for Skeleton (shadcn/ui).
 * Animated pulse placeholder with bg-accent and rounded-ui radius.
 * Used for loading states (thread list, team status, etc.)
 */
figma.connect(Skeleton, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => <Skeleton className="h-4 w-full" />,
})
