ALTER TABLE experiment_runs ADD COLUMN reproduction TEXT NOT NULL DEFAULT '{}';

CREATE TABLE run_reproductions (
    run_id BIGINT NOT NULL REFERENCES experiment_runs(id) DEFERRABLE,
    run_revision BIGINT NOT NULL,
    reviewer_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    outcome TEXT NOT NULL CHECK (outcome IN ('matched','different','inconclusive')),
    observed TEXT NOT NULL,
    updated TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
    PRIMARY KEY (run_id, run_revision, reviewer_id)
);
