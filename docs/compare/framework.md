# Framework

A **framework** gives you building blocks to construct an agent: you write the control flow, choose the persistence, and wire in models and tools yourself. A **harness** has the loop already built in, so you bring a model and instructions and go. Polyglav is a harness, so this page compares the two layers and shows how Polyglav covers the runtime while staying configurable.

## Polyglav covers the runtime, and stays flexible

Polyglav gives you the whole agent runtime out of the box, then lets you shape it through configuration rather than through code you have to maintain. The loop, tools, permissions, sessions, delegation, teams, jobs, and the fleet supervisor are ready to use. Models, providers, tools, roles, teams, skills, modes, and permissions are all data you can edit, version, and extend with plugins.

That covers the common need without a build step, and it keeps deep flexibility: you can define new roles with their own prompts and permission carves, compose teams with per-stage skills and a review loop, add tools and providers as plugins, and drive everything from configuration. When you truly need a bespoke control flow, a framework remains the right tool for that layer, and Polyglav can still serve as the runtime behind it through its CLI and HTTP API.

## Representatives

| Project | Language | License | Model | Primary focus |
|---------|----------|---------|-------|---------------|
| AutoGen | Python, .NET | Open source | Conversable agents | Multi-agent conversation and code execution |
| CrewAI | Python | MIT | Role-based crews | Role-playing agent teams and tasks |
| LangChain | Python, TypeScript | MIT | Chains and components | Combining LLM calls, tools, and data |
| LangGraph | Python, TypeScript | MIT | Stateful graph | Long-running, durable, stateful agents |
| LlamaIndex | Python, TypeScript | MIT | Data and indexes | RAG and data-centric LLM apps |
| Microsoft Agent Framework | Python, .NET | Open source | Agents and workflows | Enterprise agent SDK merging AutoGen and Semantic Kernel |
| Polyglav | Python (stdlib only) | MIT | Ready harness | Runnable agent core with orchestration |

## Profiles

### AutoGen
A framework for multi-agent conversations, where agents talk to each other and can execute code. It shines for research and complex multi-agent dialogue inside your own application.

### CrewAI
A Python framework for role-based agent teams, where each agent has a role, goal, and backstory and executes tasks. The crew metaphor maps naturally onto real workflows.

### LangChain
A broad framework for composing LLM calls, tools, retrievers, and memory, with a large integration surface. It is a toolkit for assembling exactly the pipeline you need.

### LangGraph
LangChain's low-level orchestration runtime built on a state graph, with durable checkpointers, interrupts for human-in-the-loop, and long-running execution. It gives fine-grained control over every step.

### LlamaIndex
A data framework for connecting LLMs to data, with indexes, retrievers, and RAG pipelines. It is the tool for retrieval-heavy applications.

### Microsoft Agent Framework
Microsoft's SDK for building agents and workflows, consolidating ideas from AutoGen and Semantic Kernel for Python and .NET. It targets enterprise application integration.

## Why teams choose Polyglav

- A working agent from the first command, with the loop, tools, and orchestration already assembled.
- Extensive configurability through data: types, teams, skills, modes, permissions, tools, and providers.
- Plugin extensibility for tools, providers, commands, services, types, teams, skills, and eval fixtures.
- Both interactive and programmatic: a REPL, a headless CLI, and an HTTP API from the same loop.
- Zero external dependencies, so there is no framework dependency tree to manage.

## When to choose

| Scenario | Pick | Why |
|----------|------|-----|
| The agent is one feature inside a larger application | A framework | You control the flow and embed the runtime |
| A bespoke graph or non-linear orchestration | LangGraph, LangChain | You design nodes, edges, and persistence |
| Role-based research teams or multi-agent dialogue | CrewAI, AutoGen | Purpose-built multi-agent abstractions |
| Retrieval and data-centric pipelines | LlamaIndex | Indexes, retrievers, and RAG |
| A working terminal, CLI, or HTTP agent with no build step | Polyglav | Harness ships the loop, tools, and orchestration |

## References

- https://github.com/crewAIInc/crewAI
- https://github.com/polyglav/polyglav
- https://github.com/langchain-ai/langchain
- https://github.com/langchain-ai/langgraph
- https://github.com/microsoft/agent-framework
- https://github.com/microsoft/autogen
- https://github.com/run-llama/llama_index
