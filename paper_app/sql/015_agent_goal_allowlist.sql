ALTER TABLE agent_goals ALTER COLUMN agent_id DROP NOT NULL;
ALTER TABLE agent_goals ALTER COLUMN agent_role DROP NOT NULL;
ALTER TABLE agent_goals ADD CHECK ((agent_id IS NULL) = (agent_role IS NULL));

CREATE TABLE agent_goal_readers (
    goal_id BIGINT NOT NULL REFERENCES agent_goals(id) DEFERRABLE,
    agent_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    agent_role TEXT NOT NULL CHECK (agent_role IN ('local','cloud')),
    PRIMARY KEY (goal_id,agent_id)
);
CREATE INDEX agent_goal_readers_agent ON agent_goal_readers(agent_id,goal_id);
INSERT INTO agent_goal_readers SELECT id,agent_id,agent_role FROM agent_goals WHERE agent_id IS NOT NULL;
