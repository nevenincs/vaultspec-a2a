import figma from '@figma/code-connect'
import { ErrorAlert } from './error-alert'

/**
 * Code Connect mapping for ErrorAlert.
 * Renders a stream-level error with AlertTriangle icon and status-error styling.
 * Also surfaces the error through the centralized logger system.
 * Used for backend errors surfaced via the WebSocket event stream.
 *
 * Props:
 * - event: ErrorStreamEvent — { type: 'error', message, code?, ... }
 */
figma.connect(ErrorAlert, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <ErrorAlert
      event={{
        id: 'evt-7',
        type: 'error',
        thread_id: 'thread-1',
        message: 'Agent exceeded token limit',
        code: 'TOKEN_LIMIT',
        timestamp: new Date().toISOString(),
      }}
    />
  ),
})
