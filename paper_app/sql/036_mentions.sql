CREATE TABLE comment_mentions (
    comment_id BIGINT NOT NULL REFERENCES comments(id) ON DELETE CASCADE DEFERRABLE,
    account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE DEFERRABLE,
    PRIMARY KEY(account_id,comment_id)
);
CREATE TABLE document_mentions (
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE DEFERRABLE,
    account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE DEFERRABLE,
    PRIMARY KEY(account_id,document_id)
);
CREATE INDEX comment_mentions_content ON comment_mentions(comment_id);
CREATE INDEX document_mentions_content ON document_mentions(document_id);
