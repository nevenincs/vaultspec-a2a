import figma from '@figma/code-connect';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog';
import { Button } from './button';

/**
 * Code Connect mapping for AlertDialog (Radix UI + shadcn/ui).
 * Blocking modal for critical actions and permission requests.
 * Used by PermissionModal (open={true} always, no trigger button needed).
 * Background interaction is disabled while open.
 */
figma.connect(
  AlertDialog,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      title: figma.string('Title'),
      description: figma.string('Description'),
    },
    example: (props) => (
      <AlertDialog open={true}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{props.title}</AlertDialogTitle>
            <AlertDialogDescription>{props.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button variant="outline">Cancel</Button>
            <Button>Confirm</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    ),
  },
);
