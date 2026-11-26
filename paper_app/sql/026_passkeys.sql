CREATE TABLE passkeys (
    credential_id BYTEA PRIMARY KEY, account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    public_key BYTEA NOT NULL, sign_count BIGINT NOT NULL, label TEXT NOT NULL, created BIGINT NOT NULL,
    origin TEXT NOT NULL
);
CREATE INDEX passkeys_account ON passkeys(account_id);

CREATE TABLE passkey_challenges (
    token TEXT PRIMARY KEY, challenge BYTEA NOT NULL, origin TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('register','login')),
    session_hash BYTEA, expires BIGINT NOT NULL
);
CREATE INDEX passkey_challenges_expiry ON passkey_challenges(expires);
