import figma from '@figma/code-connect';
import { ScrollArea } from './scroll-area';

/**
 * Code Connect mapping for ScrollArea (Radix UI + shadcn/ui).
 * Custom scrollbar with 2.5px width and rounded thumb.
 * Used extensively in Sidebar (thread list), InspectorPanel (content),
 * and MessageStream (event list).
 *
 * Usage: wrap content in ScrollArea. The scrollbar auto-hides on overflow.
 */
figma.connect(
  ScrollArea,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <ScrollArea className="h-full w-full">
        <div>{/* content */}</div>
      </ScrollArea>
    ),
  },
);
