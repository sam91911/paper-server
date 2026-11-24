CREATE TABLE human_public_keys (
    account_id BIGINT PRIMARY KEY REFERENCES accounts(id) DEFERRABLE, public_key BYTEA NOT NULL UNIQUE
);

CREATE TABLE human_key_challenges (
    token_hash BYTEA PRIMARY KEY, username TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('register', 'login', 'attach')), expires BIGINT NOT NULL
);
