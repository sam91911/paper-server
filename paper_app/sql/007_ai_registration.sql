CREATE TABLE ai_invites (
    token_hash BYTEA PRIMARY KEY, username TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('local', 'cloud')), expires BIGINT NOT NULL
);

CREATE TABLE ai_public_keys (
    account_id BIGINT PRIMARY KEY REFERENCES accounts(id) DEFERRABLE,
    public_key BYTEA NOT NULL
);

CREATE TABLE ai_challenges (
    token_hash BYTEA PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES ai_public_keys(account_id) ON DELETE CASCADE DEFERRABLE,
    expires BIGINT NOT NULL
);
