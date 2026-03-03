import figma from '@figma/code-connect';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from './dialog';
import { Button } from './button';

/**
 * Code Connect mapping for Dialog (Radix UI + shadcn/ui).
 * Modal dialog with overlay, backdrop blur, and animate-in/out transitions.
 * Used for contextual modals that aren't permission requests.
 * (Permission requests use AlertDialog.)
 */
figma.connect(
  Dialog,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      title: figma.string('Title'),
      description: figma.string('Description'),
    },
    example: (props) => (
      <Dialog>
        <DialogTrigger asChild>
          <Button variant="outline">Open</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{props.title}</DialogTitle>
            <DialogDescription>{props.description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button>Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    ),
  },
);
