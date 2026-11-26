ALTER TABLE papers ADD COLUMN source_url TEXT NOT NULL DEFAULT '';

CREATE TABLE paper_metadata_access (
    paper_id BIGINT PRIMARY KEY REFERENCES paper_access(paper_id) DEFERRABLE,
    audience TEXT NOT NULL CHECK (audience IN ('owner', 'users', 'local', 'all', 'ai'))
);
