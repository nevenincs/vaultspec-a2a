import figma from '@figma/code-connect';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  CardAction,
} from './card';

/**
 * Code Connect mapping for Card (shadcn/ui).
 * Container with bg-card, rounded-ui radius, border.
 * Uses CSS container query (@container/card-header) for responsive layout.
 * Supports optional CardAction in the header (right-aligned).
 */
figma.connect(
  Card,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    props: {
      title: figma.string('Title'),
      description: figma.string('Description'),
    },
    example: (props) => (
      <Card>
        <CardHeader>
          <CardTitle>{props.title}</CardTitle>
          <CardDescription>{props.description}</CardDescription>
        </CardHeader>
        <CardContent>{/* content */}</CardContent>
        <CardFooter>{/* footer */}</CardFooter>
      </Card>
    ),
  },
);
