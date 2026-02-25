---
title: A2A Streaming and Asynchronous Operations
source: https://a2a-protocol.org/latest/topics/streaming-and-async/
relevance: 10
---

## A2A Streaming and Asynchronous Operations

 long-running tasks through two primary mechanisms:
**Server-Sent Events (SSE)** for continuous connections and **Push Notifications
(Webhooks)** for disconnected or ultra-long-running scenarios.

## 1. Streaming with Server-Sent Events (SSE)

Used when the client can maintain an active HTTP connection.

### SSE Protocol Specifics

- **Capability Requirement**: Agent Card must have `capabilities.streaming: true`.
- **Initiation**: Client calls `SendStreamingMessage` RPC.
- **Connection**:
  - Status: `HTTP 200 OK`
  - Header: `Content-Type: text/event-stream`
- **Payload Structure**:
  - Format: JSON-RPC 2.0 Response (`SendStreamingMessageResponse`).
  - Result Fields:
    - `Task`: Current state of work.
    - `TaskStatusUpdateEvent`: Lifecycle changes (e.g., `working` ->
      `input-required`).
    - `TaskArtifactUpdateEvent`: Incremental data/files.
      - Fields: `append` (boolean), `lastChunk` (boolean) for reassembly.
- **Termination**: Stream closes on terminal states: `COMPLETED`, `FAILED`,
  `CANCELED`, `REJECTED`, or `INPUT_REQUIRED`.
- **Resubscription**: If disconnected, use `SubscribeToTask` RPC to reconnect.

## 2. Push Notifications (Webhooks)

Used for tasks lasting minutes/days or for clients like mobile/serverless that
cannot maintain persistent connections.

### Push Protocol Specifics

- **Capability Requirement**: Agent Card must have
  `capabilities.pushNotifications: true`.
- **Configuration**: `PushNotificationConfig` object.
  - `url`: HTTPS webhook URL.
  - `token`: Optional client-side validation token.
  - `authentication`: Details for A2A Server to authenticate to the webhook.
- **Trigger**: Significant state changes (Terminal, `input-required`,
  `auth-required`).
- **Payload**: `StreamResponse` object (matches SSE format).
  - Contains: `task`, `message`, `statusUpdate`, or `artifactUpdate`.
- **Client Flow**: Receive notification -> Extract `taskId` -> Call `GetTask` RPC
  for full state.

## 3. Security Architecture

### Server-Side (Sender) Security

- **SSRF Mitigation**: Webhook URL validation via allowlisting, ownership
  verification (challenge-response), and egress firewalls.
- **Authentication**: Server must authenticate to the webhook using the scheme
  in `PushNotificationConfig.authentication` (Bearer/OAuth2, API Keys, HMAC, or
  mTLS).

### Client-Side (Receiver) Security

- **Verification**: Rigorous verification of incoming requests (JWT signatures,
  HMAC, or API keys).
- **Replay Protection**:
  - Timestamps: Reject old notifications.
  - Nonces/IDs: Use `jti` (JWT ID) or event IDs to prevent duplicate processing.
- **Key Management**: Use JWKS (JSON Web Key Set) for asymmetric key rotation.

### Visual Transcription: Asymmetric Key Flow (JWT + JWKS)

1. **Configuration**: Client sets `PushNotificationConfig` with
   `authentication.scheme: "Bearer"`.
2. **Notification (Server)**:
    - Generates JWT signed with **Private Key**.
    - **JWT Header**: Includes `alg` and `kid` (Key ID).
    - **JWT Claims**: `iss` (issuer), `aud` (audience), `iat` (issued at), `exp`
      (expires), `jti` (JWT ID), and `taskId`.
    - **Public Key**: Made available via a **JWKS endpoint**.
3. **Verification (Client Webhook)**:
    - Extracts JWT from `Authorization` header.
    - Identifies `kid` from header.
    - Fetches/Caches Public Key from Server's **JWKS endpoint**.
    - Verifies signature and validates claims (`iss`, `aud`, `iat`, `exp`,
      `jti`).
    - Validates `PushNotificationConfig.token` if present.
