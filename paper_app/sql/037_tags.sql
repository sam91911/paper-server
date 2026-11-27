CREATE TABLE paper_tags (
    paper_id BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE DEFERRABLE,
    tag TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(paper_id,tag)
);
CREATE INDEX paper_tags_filter ON paper_tags(tag,paper_id);

CREATE TABLE document_tags (
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE DEFERRABLE,
    tag TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(document_id,tag)
);
CREATE INDEX document_tags_filter ON document_tags(tag,document_id);
