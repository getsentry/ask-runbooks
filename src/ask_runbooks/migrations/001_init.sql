CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source document (a markdown file, a Notion page, a GitHub file).
-- hash is used to skip re-indexing unchanged docs during sync.
CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    source      TEXT NOT NULL,           -- 'local', 'github', 'notion'
    doc_type    TEXT NOT NULL,           -- 'runbook', 'incident', 'architecture', 'code'
    path        TEXT NOT NULL,           -- original path or URL (unique per source)
    title       TEXT,
    content     TEXT NOT NULL,
    hash        TEXT NOT NULL,           -- sha256 of content, for change detection
    synced_at   TIMESTAMPTZ DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}',
    UNIQUE(source, path)
);

-- One row per chunk. A document is split into overlapping chunks for indexing.
-- embedding is a 384-dimensional vector produced by all-MiniLM-L6-v2.
-- Each dimension encodes some aspect of meaning — proximity in this space = semantic similarity.
CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    -- 768 dims: the size of nomic-embed-text-v1.5's output space.
    -- Stored as a pgvector column — supports fast ANN search with <=> (cosine distance).
    embedding   vector(768),
    UNIQUE(document_id, chunk_index)
);

-- GIN index: accelerates full-text keyword search (tsvector/tsquery).
CREATE INDEX IF NOT EXISTS chunks_fts
    ON chunks USING GIN (to_tsvector('english', content));

-- HNSW index: approximate nearest-neighbour search over embedding vectors.
-- Builds a multi-layer graph for fast, accurate search at any scale.
-- Slower to build than IVFFlat but faster at query time and needs no tuning as corpus grows.
CREATE INDEX IF NOT EXISTS chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops);
