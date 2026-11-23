CREATE TABLE metric_corrections (
    metric_id BIGINT NOT NULL REFERENCES metrics(cursor_id) DEFERRABLE,
    revision BIGINT NOT NULL,
    editor_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    page BIGINT NOT NULL, metric TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL,
    conditions TEXT NOT NULL, evidence TEXT NOT NULL, reason TEXT NOT NULL,
    created TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
    PRIMARY KEY (metric_id,revision)
);
CREATE TABLE metric_editors (
    metric_id BIGINT NOT NULL REFERENCES metrics(cursor_id) DEFERRABLE,
    account_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    PRIMARY KEY (metric_id,account_id)
);
CREATE INDEX metrics_paper_cursor ON metrics(paper_id,cursor_id);
