# ask-runbooks

**Talk to your runbooks!**

A project week experiment — natural language Q&A over runbooks and incident documents. Syncs from Notion and other sources. Answers are based on actual docs and sources are linked.

![screenshot]

## How it works

### Indexing documents

`sync-runbooks` indexes documents from configured sources into Postgres:

1. **Fetch from sources**
   - Docs can live in many different systems, such as Notion and Github
   - Links back to the original source are preserved so they can be referenced later
   - Each source is tagged with a doc type (`runbook`, `incident`, etc.) which drives how docs are searched and displayed
2. **Split docs into chunks**
   - The current embedding model (`all-mpnet-base-v2`) has a max input of 384 tokens, so docs need to be split before embedding so chunks
   - We split docs into smaller overlapping sections (~1500 characters each)
   - Smaller chunks are more meanintful, overlapping ensures nothing falls through the cracks at the boundaries
3. **Convert chunks to vector embeddings**
   - Each chunk is converted into a 768-dimensional vector using `sentence-transformers` running `all-mpnet-base-v2` locally on-device. This is chosen for this experiment as it runs well on Apple Silicon with no extra dependencies; a stronger model may be swapped in later.
   - This enables semantic search - "database went down" should also match a doc about "postgres outage"
4. **Store documents and chunks in Postgres**
   - Documents are stored in a `documents` table; each chunk and its vector are stored together in a `chunks` table, using the `vector(768)` type from pgvector
   - Each doc's content is hashed — on re-sync, only changed docs are re-chunked and re-embedded, so syncing is fast
   - Note: deleted docs are not currently removed from the index

### Answering questions

`ask-runbooks-web` starts the web UI.

Each question submitted goes through a multi-step pipeline:

1. **Generate a hypothetical answer first (HyDE)**
   - The configured LLM (defined in `config.yaml`) generates a short hypothetical document that would answer the question.
   - The hypothetical answer is shaped like a real doc, so its vector lands closer to actual docs than the raw question
2. **Expand acronyms**
   - Internal terms in the question (e.g. `EAP`, `SnS`, `POP`) are expanded using a glossary defined in `config.yaml`
   - This improves search quality and ensures the LLM uses consistent terminology in its answer
   - Note: Expansion is done via regex currently with no context awareness, so very short or common terms (e.g. `ST`) could match unintended words
3. **Find relevant chunks with hybrid search**
   - Run separately for incidents and runbooks — incidents tend to dominate combined results, crowding out runbooks
   - *Keyword search* — Postgres full-text search against chunk text; finds exact matches on things like service names, error codes, and version numbers
   - *Semantic search* — embeds the hypothetical answer and finds nearby vectors in the `chunks` table (pgvector); finds conceptually related docs even with no shared words. Chunks beyond a cosine distance of `0.7` are filtered out before reranking
   - Results are merged with Reciprocal Rank Fusion (RRF) — rewards docs that rank highly in both keyword and semantic results
4. **Re-rank candidates with a cross-encoder**
   - Scores each (query, chunk) pair together using `cross-encoder/ms-marco-MiniLM-L-6-v2` (small question answering model)
   - Results below `RERANKER_THRESHOLD = -2.0` are dropped
   - Incidents are boosted by recency — newer INC numbers score up to 20% higher, so recent incidents surface over older ones with similar relevance
5. **Generate an answer**
   - Top results passed to the LLM with conversation history
   - Answer and sources returned to the user

## Answer quality, evals, and tuning

### 1. Retrieval quality

- The eval set (`eval/cases.yaml`) contains questions paired with the incidents and runbooks we'd expect to be returned. `eval/run_eval.py` scores recall per case — use this to measure the impact of changes before committing to them.
- Things to try: changing the embedding model, reranker, toggling HyDE, chunk size, search parameters, max distance


### 2. LLM and prompting

- Things to try: swapping the LLM, tuning the system prompt, adjusting conversation history length

