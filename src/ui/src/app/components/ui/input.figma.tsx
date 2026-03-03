import figma from '@figma/code-connect';
import { Input } from './input';

/**
 * Code Connect mapping for Input (shadcn/ui).
 * Standard text input with rounded-control radius, h-9 height,
 * border-input border, and focus-visible ring.
 * Supports all HTML input types and aria-invalid state.
 */
figma.connect(
  Input,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      placeholder: figma.string('Placeholder'),
      disabled: figma.boolean('Disabled'),
    },
    example: (props) => (
      <Input placeholder={props.placeholder} disabled={props.disabled} />
    ),
  },
);
