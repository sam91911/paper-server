CREATE TABLE public_papers (
    paper_id BIGINT PRIMARY KEY REFERENCES papers(id) DEFERRABLE,
    title TEXT NOT NULL, doi TEXT NOT NULL, source_url TEXT NOT NULL, summary TEXT NOT NULL
);
