ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'document' CHECK (kind IN ('document', 'discussion'));
ALTER TABLE documents ADD COLUMN scheduled_at BIGINT;
ALTER TABLE comments ADD COLUMN scheduled_at BIGINT;

CREATE TABLE document_versions (
    document_id BIGINT NOT NULL REFERENCES documents(id) DEFERRABLE,
    revision BIGINT NOT NULL,
    title TEXT NOT NULL,
    markdown TEXT NOT NULL,
    source_url TEXT NOT NULL,
    author TEXT NOT NULL,
    saved TEXT NOT NULL,
    PRIMARY KEY (document_id, revision)
);
INSERT INTO document_versions(document_id,revision,title,markdown,source_url,author,saved)
SELECT d.id,d.revision,d.title,d.markdown,d.source_url,a.username,d.updated
FROM documents d JOIN accounts a ON a.id=d.owner_id;

CREATE TABLE thread_votes (
    kind TEXT NOT NULL CHECK (kind IN ('discussion', 'comment')),
    target_id BIGINT NOT NULL,
    account_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    value BIGINT NOT NULL CHECK (value IN (-1, 1)),
    PRIMARY KEY (kind,target_id,account_id)
);
