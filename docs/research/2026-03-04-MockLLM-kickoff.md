# MockLLM - The missing mock layer needed to test frontend implementation against

The codebase's backend has been hardened recently. The internals of the full langraph
pipeline has been exposed to the backend edges (json rpc, websocket interfaces) in anticipation of the frontend work and tanstack work beginning to scaffold against the backend. BUT!

THe current architecture does not have any capability to decouple form the live LLMs whilst still prove mock llms that have full feature parity with real llms.

I suggest we implement a full featured `MockLLM` provider.
Immediate question: should this agent be a native online sdk or acp based agent?


## Mock architecture

The MockLLM is only meaningful if it pairs with a mock agent toml definition and a mock team toml team preset so that the real LangGraph pipeline can utilise a full mock architecture without the need to call any live services.

## Is this a solved problem?

Task must kick off with extensive online research to identiy capabilities and existing code landscape and projects: has anybody implemented a programmable mock llm in python already? Does LangGraph provide this functionality?

Tool usage mandate: use context7 and LangChain MCPs for user doc searches.


## MockLLM behaviour

We need full feature parity with real LLMs. Remember that the goal is to provide fake running teams so that the ui camn run against a fully saturated datastream, interact with the mock services, that delegates ask for permissions and halts, produces errors.

I suggest if the research backs it up that we implement different internal "conversation playbacks" that correctly sequence real agent behaviours with agent responses - agent thinking - agent tool calls - agent reposnes - agent permission requests. The emphasis is on full feature parity.

## What the UI should see

Multiple teams:
- A team that has concluded work. There's a history for each agents, but work has already
finished. Team has shut down and finished running in the past with success.
- A team that finished running with a failiure: what kind of failiures are defined? tool calling errors?
- a team that is invalid - some sort of internal issue, not sure what the error conditions might be the LangGraph defines - but dirty, unreachable service, corrupted, invalid agent definitions, invalid team definition, corrupted entries. Needs research and proper discovery of the LangGraph error states.
- Team that is fully autonomous and is working in tandem "solving a problem". No user inut required, agents are taking turns and are waiting on each other. Orchestrator. Agents are calling tools, think internally.
- A team that is running but require user input - they cycle between work, then an interrupt so that the user needs to manually approve. Must handle both reject and accept.
- A single coder team
- A team that has multiple memebers.

The mock infrastructure must be full featured so the ui can receive full trace output.


## Context (not much)

The docs/audits folder contains traces and findings, as well as the docs/plans folders. If you find the relevant docs you can see exactly the work that was done.

## Obsolete code to retire

Fixture server's is very likely obsolete after this. We do not want to reinvent the wheel but instead utilise the current pipeline with a full feature mock LLM.