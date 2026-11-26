ALTER TABLE agent_goals ADD COLUMN attention TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_goal_events ADD COLUMN research TEXT;
UPDATE agent_goals g SET attention='approval'
WHERE g.require_approval AND g.status='paused' AND EXISTS (
    SELECT 1 FROM agent_goal_events e WHERE e.goal_id=g.id AND e.revision=g.revision
    AND e.action IN ('create','release')
);

CREATE TABLE agent_schedules (
    agent_id BIGINT PRIMARY KEY REFERENCES accounts(id),
    interval_seconds INTEGER NOT NULL,
    next_run BIGINT,
    failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agent_schedules(agent_id),
    started BIGINT NOT NULL,
    deadline BIGINT NOT NULL,
    finished BIGINT,
    success BOOLEAN,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX agent_runs_history ON agent_runs(agent_id, started DESC, id);
CREATE UNIQUE INDEX agent_runs_active ON agent_runs(agent_id) WHERE finished IS NULL;
