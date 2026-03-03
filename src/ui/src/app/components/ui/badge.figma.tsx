import figma from '@figma/code-connect';
import { Badge } from './badge';

/**
 * Code Connect mapping for Badge (shadcn/ui + CVA).
 * Variants: default, secondary, destructive, outline
 * Uses rounded-control radius token.
 */
figma.connect(
  Badge,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      variant: figma.enum('Variant', {
        Default: 'default',
        Secondary: 'secondary',
        Destructive: 'destructive',
        Outline: 'outline',
      }),
      label: figma.string('Label'),
    },
    example: (props) => <Badge variant={props.variant}>{props.label}</Badge>,
  },
);
