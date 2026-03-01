import figma from '@figma/code-connect'
import { Popover, PopoverTrigger, PopoverContent } from './popover'
import { Button } from './button'

/**
 * Code Connect mapping for Popover (Radix UI + shadcn/ui).
 * Floating content panel with animate-in/out transitions.
 * Default width: w-72, sideOffset: 4, align: center.
 * Used by InputBar for team preset picker, repo/branch/tag pickers,
 * and MessageStream for context document selector.
 */
figma.connect(Popover, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline">Open</Button>
      </PopoverTrigger>
      <PopoverContent>
        <p>Popover content here</p>
      </PopoverContent>
    </Popover>
  ),
})
