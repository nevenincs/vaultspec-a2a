import figma from '@figma/code-connect'
import { PlanUpdateCard } from './plan-update-card'

/**
 * Code Connect mapping for PlanUpdateCard.
 * Compact clickable card showing plan progress (completed/total).
 * Uses palette-driven 'plan' accent color for the ListChecks icon.
 * Clicking opens the inspector panel with the full plan view.
 *
 * Props:
 * - event: PlanUpdateEvent — { type: 'plan_update', entries: PlanEntry[], ... }
 * - onInspect: (target: InspectorTarget) => void
 */
figma.connect(PlanUpdateCard, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <PlanUpdateCard
      event={{
        id: 'evt-6',
        type: 'plan_update',
        thread_id: 'thread-1',
        entries: [
          { id: '1', title: 'Scaffold project', status: 'completed', priority: 'high' },
          { id: '2', title: 'Implement API', status: 'in_progress', priority: 'high' },
          { id: '3', title: 'Write tests', status: 'pending', priority: 'medium' },
        ],
        agent_id: 'agent-1',
        agent_name: 'Planner',
        timestamp: new Date().toISOString(),
      }}
      onInspect={() => {}}
    />
  ),
})
