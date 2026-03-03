import figma from '@figma/code-connect';
import { Separator } from './separator';

/**
 * Code Connect mapping for Separator (Radix UI + shadcn/ui).
 * Horizontal: 1px height, full width. Vertical: full height, 1px width.
 * Uses bg-border color. Decorative by default (not announced to screen readers).
 */
figma.connect(
  Separator,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      orientation: figma.enum('Orientation', {
        Horizontal: 'horizontal',
        Vertical: 'vertical',
      }),
    },
    example: (props) => <Separator orientation={props.orientation} />,
  },
);
