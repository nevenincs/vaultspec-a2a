import figma from '@figma/code-connect'
import { Button } from './button'

/**
 * Code Connect mapping for Button (shadcn/ui + CVA).
 * Variants: default, destructive, outline, secondary, ghost, link, terminal
 * Sizes: default (h-9), sm (h-8), lg (h-10), icon (size-9)
 *
 * Uses rounded-control radius token. Keyboard-only focus ring via focus-visible.
 * The 'terminal' variant uses oxide-terminal-bg with monospace font at 0.75rem.
 */
figma.connect(Button, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  props: {
    variant: figma.enum('Variant', {
      Default: 'default',
      Destructive: 'destructive',
      Outline: 'outline',
      Secondary: 'secondary',
      Ghost: 'ghost',
      Link: 'link',
      Terminal: 'terminal',
    }),
    size: figma.enum('Size', {
      Default: 'default',
      Small: 'sm',
      Large: 'lg',
      Icon: 'icon',
    }),
    disabled: figma.boolean('Disabled'),
    label: figma.string('Label'),
  },
  example: (props) => (
    <Button variant={props.variant} size={props.size} disabled={props.disabled}>
      {props.label}
    </Button>
  ),
})
