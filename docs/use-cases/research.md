# Research and academia

Research work is built on traceable, reproducible steps, and unpublished results can be commercially or legally sensitive. The local-first storage and complete session logs match both requirements: the data and the reasoning stay on your machine, and every query, source, and conclusion is reconstructable afterward. The shared foundation is in [index.md](index.md).

## Why it fits

- **Confidentiality for unpublished work**. Config and sessions live on your disk, and a local model (Ollama via `/connect`) keeps everything on premises. Grants, embargoes, and pre-publication data never touch a third-party service.
- **A reproducible research trail**. Every session persists the question, the sources fetched, the tool calls, and the reasoning. That is a literature-search log, a data-analysis notebook, and a citation trail in one.
- **Grounded answers with sources**. `web_search` and `web_fetch` (alias `open`) pull current literature and surface the sources, while file tools keep the model answering from your own corpus of papers, notes, and lab exports rather than from memory.
- **No IT approval needed**. A standard-library Python package installs anywhere and runs headless, so a lab or a single researcher can adopt it without a managed environment.

## Fit by use case

- **Literature review**. Search, fetch, and summarize papers and preprints, with the trail saved per session. `/session save litreview-<topic>` keeps topics as separate threads.
- **Corpus queries**. Point an agent at a folder of papers or notes (`polyglav serve --path ~/papers`) and ask comparative questions, with `grep` and `file_read` grounding every answer in the actual text.
- **Data analysis support**. Describe datasets and plan analyses in plain language, draft analysis code and experiment notes, and prepare result summaries, with execution kept behind the `ask` gate on `run_command`.
- **Writing support**. Draft methods, related-work, and appendix text from the corpus with citations attached, then use `file_write` for review.
- **Lab notebooks and logs**. Sessions double as a structured, timestamped lab notebook per project or experiment.

## Gaps and planned

Deep research features are planned: local RAG with embeddings and a vector store for semantic search over your corpus, interactive CSV and SQL data analysis, and notebook mode. These track [TODO.md](../../TODO.md). Until then, `grep`-based full-text search over a converted corpus covers most needs.

## Get started

1. Install with `pip install polyglav`, then run `polyglav`, or `polyglav serve --path ~/papers` for a headless corpus agent.
2. `/connect` to a provider. Prefer a local model for embargoed or export-controlled material.
3. Scope permissions with `tool_permission.bash: ask`, deny anything unused with `tools.deny`, and keep write tools out of read-only review agents.
4. Start a session per topic. The complete log under `.polyglav/sessions/` is your reproducibility record.
