ALTER TABLE ai_invites ADD COLUMN invite_id TEXT;
ALTER TABLE ai_invites ADD COLUMN issuer_id BIGINT REFERENCES accounts(id) DEFERRABLE;
ALTER TABLE ai_invites ADD COLUMN rotate_id BIGINT REFERENCES accounts(id) DEFERRABLE;
ALTER TABLE ai_invites ADD COLUMN created BIGINT;
ALTER TABLE ai_invites ADD COLUMN used_at BIGINT;
ALTER TABLE ai_invites ADD COLUMN canceled_at BIGINT;
ALTER TABLE ai_public_keys ADD COLUMN last_authenticated BIGINT;
CREATE UNIQUE INDEX ai_invites_identity ON ai_invites(invite_id);
CREATE INDEX ai_invites_issuer ON ai_invites(issuer_id,created);

CREATE TABLE ai_operators (
    agent_id BIGINT PRIMARY KEY REFERENCES accounts(id) DEFERRABLE,
    operator_id BIGINT NOT NULL REFERENCES accounts(id) DEFERRABLE
);
