import figma from '@figma/code-connect';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from './tooltip';
import { Button } from './button';

/**
 * Code Connect mapping for Tooltip (Radix UI + shadcn/ui).
 * Uses primary background for tooltip content, with an arrow indicator.
 * delayDuration defaults to 0 for immediate display.
 * Wraps trigger in TooltipProvider automatically.
 *
 * Usage: wrap TooltipTrigger around the trigger element,
 * TooltipContent holds the tooltip text.
 */
figma.connect(
  Tooltip,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      label: figma.string('Label'),
    },
    example: (props) => (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon">
            ?
          </Button>
        </TooltipTrigger>
        <TooltipContent>{props.label}</TooltipContent>
      </Tooltip>
    ),
  },
);
