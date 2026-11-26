CREATE TABLE ai_goal_delegates (
    agent_id BIGINT NOT NULL REFERENCES ai_operators(agent_id) DEFERRABLE,
    delegate_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE,
    PRIMARY KEY (agent_id, delegate_id)
);
CREATE INDEX ai_goal_delegates_account ON ai_goal_delegates(delegate_id, agent_id);
