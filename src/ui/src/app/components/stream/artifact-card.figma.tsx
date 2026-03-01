import figma from '@figma/code-connect'
import { ArtifactCard } from './artifact-card'

/**
 * Code Connect mapping for ArtifactCard.
 * Compact clickable card showing a file artifact (created or modified).
 * Uses palette-driven accent color for the FileCode icon. Clicking opens
 * the inspector panel with a diff view or full file content.
 *
 * Props:
 * - event: ArtifactEvent — { type: 'artifact', filename, content, old_content?, ... }
 * - onInspect: (target: InspectorTarget) => void
 */
figma.connect(ArtifactCard, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <ArtifactCard
      event={{
        id: 'evt-5',
        type: 'artifact',
        thread_id: 'thread-1',
        artifact_id: 'art-1',
        filename: 'src/lib/api.py',
        content: '# API module\n...',
        complete: true,
        agent_id: 'agent-1',
        agent_name: 'Coder',
        timestamp: new Date().toISOString(),
      }}
      onInspect={() => {}}
    />
  ),
})
