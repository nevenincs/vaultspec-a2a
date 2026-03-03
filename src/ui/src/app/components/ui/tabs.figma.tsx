import figma from '@figma/code-connect';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './tabs';

/**
 * Code Connect mapping for Tabs (Radix UI + shadcn/ui).
 * Uses rounded-ui radius and muted background for the tab list.
 * Active tab: card background, subtle border, transition.
 * Used in InspectorPanel for switching between views (content/diff/plan).
 */
figma.connect(
  Tabs,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <Tabs defaultValue="tab1">
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
          <TabsTrigger value="tab2">Tab 2</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1">Content 1</TabsContent>
        <TabsContent value="tab2">Content 2</TabsContent>
      </Tabs>
    ),
  },
);
