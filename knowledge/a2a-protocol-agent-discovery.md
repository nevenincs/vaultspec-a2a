---
name: "A2A Agent Discovery"
date: 2026-25-02
type: reference
summary: "Discovery strategies including well-known URI, curated registries, direct configuration, and security considerations for Agent Cards."
maturity: 80
---

# A2A Agent Discovery Reference

To collaborate using the Agent2Agent (A2A) protocol, AI agents need to first
find each other and understand their capabilities. A2A standardizes agent
self-descriptions through the Agent Card. However, discovery methods for these
Agent Cards vary by environment and requirements. The Agent Card defines what an
agent offers. Various strategies exist for a client agent to discover these
cards. The choice of strategy depends on the deployment environment and security
requirements.

## THE ROLE OF THE AGENT CARD

The Agent Card is a JSON document that serves as a digital "business card" for
an A2A Server (the remote agent). It is crucial for agent discovery and
interaction. The key information included in an Agent Card is as follows:

* **Identity:** Includes name, description, and provider information.
* **Service Endpoint:** Specifies the url for the A2A service.
* **A2A Capabilities:** Lists supported features such as streaming or
  pushNotifications.
* **Authentication:** Details the required schemes (e.g., "Bearer", "OAuth2").
* **Skills:** Describes the agent's tasks using AgentSkill objects, including
  id, name, description, inputModes, outputModes, and examples.

Client agents use the Agent Card to determine an agent's suitability, structure
requests, and ensure secure communication.

## DISCOVERY STRATEGIES

The following sections detail common strategies used by client agents to
discover remote Agent Cards:

### 1. WELL-KNOWN URI

This approach is recommended for public agents or agents intended for broad
discovery within a specific domain.

* **Mechanism:** A2A Servers make their Agent Card discoverable by hosting it at
  a standardized, well-known URI on their domain. The standard path is
  `https://{agent-server-domain}/.well-known/agent-card.json`, following the
  principles of RFC 8615.
* **Process:**
    1. A client agent knows or programmatically discovers the domain of a
       potential A2A Server (e.g., `smart-thermostat.example.com`).
    2. The client performs an HTTP GET request to
       `https://smart-thermostat.example.com/.well-known/agent-card.json`.
    3. If the Agent Card exists and is accessible, the server returns it as a
       JSON response.
* **Advantages:**
  * Ease of implementation
  * Adheres to standards
  * Facilitates automated discovery
* **Considerations:**
  * Best suited for open or domain-controlled discovery scenarios.
  * Authentication is necessary at the endpoint serving the Agent Card if it
    contains sensitive details.

### 2. CURATED REGISTRIES (CATALOG-BASED DISCOVERY)

This approach is employed in enterprise environments or public marketplaces,
where Agent Cards are often managed by a central registry. The curated registry
acts as a central repository, allowing clients to query and discover agents
based on criteria like "skills" or "tags".

* **Mechanism:** An intermediary service (the registry) maintains a collection
  of Agent Cards. Clients query this registry to find agents based on various
  criteria (e.g., skills offered, tags, provider name, capabilities).
* **Process:**
    1. A2A Servers publish their Agent Cards to the registry.
    2. Client agents query the registry's API, and search by criteria such as
       "specific skills".
    3. The registry returns matching Agent Cards or references.
* **Advantages:**
  * Centralized management and governance.
  * Capability-based discovery (e.g., by skill).
  * Support for access controls and trust frameworks.
  * Applicable in both private and public marketplaces.
* **Considerations:**
  * Requires deployment and maintenance of a registry service.
  * The current A2A specification does not prescribe a standard API for
    curated registries.

### 3. DIRECT CONFIGURATION / PRIVATE DISCOVERY

This approach is used for tightly coupled systems, private agents, or
development purposes, where clients are directly configured with Agent Card
information or URLs.

* **Mechanism:** Client applications utilize hardcoded details, configuration
  files, environment variables, or proprietary APIs for discovery.
* **Process:** The process is specific to the application's deployment and
  configuration strategy.
* **Advantages:** This method is straightforward for establishing connections
  within known, static relationships.
* **Considerations:**
  * Inflexible for dynamic discovery scenarios.
  * Changes to Agent Card information necessitate client reconfiguration.
  * Proprietary API-based discovery also lacks standardization.

## SECURING AGENT CARDS

Agent Cards include sensitive information, such as:

* URLs for internal or restricted agents.
* Descriptions of sensitive skills.

### PROTECTION MECHANISMS

To mitigate risks, the following protection mechanisms should be considered:

* **Authenticated Agent Cards:** We recommend the use of authenticated extended
  agent cards for sensitive information or for serving a more detailed version
  of the card.
* **Secure Endpoints:** Implement access controls on the HTTP endpoint serving
  the Agent Card (e.g., `/.well-known/agent-card.json` or registry API). The
  methods include:
  * Mutual TLS (mTLS)
  * Network restrictions (e.g., IP ranges)
  * HTTP Authentication (e.g., OAuth 2.0)
* **Registry Selective Disclosure:** Registries return different Agent Cards
  based on the client's identity and permissions.

Any Agent Card containing sensitive data must be protected with authentication
and authorization mechanisms. The A2A specification strongly recommends the use
of out-of-band dynamic credentials rather than embedding static secrets within
the Agent Card.

## FUTURE CONSIDERATIONS

The A2A community explores standardizing registry interactions or advanced
discovery protocols.
