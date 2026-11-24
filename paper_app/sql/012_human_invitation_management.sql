ALTER TABLE human_invites ADD COLUMN invite_id TEXT;
ALTER TABLE human_invites ADD COLUMN issuer_id BIGINT REFERENCES accounts(id) DEFERRABLE;
CREATE UNIQUE INDEX human_invites_identity ON human_invites(invite_id);
CREATE INDEX human_invites_issuer ON human_invites(issuer_id,expires);
