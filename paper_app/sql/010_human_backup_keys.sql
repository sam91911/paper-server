ALTER TABLE human_public_keys ADD COLUMN key_id TEXT;
ALTER TABLE human_public_keys ADD COLUMN label TEXT NOT NULL DEFAULT 'Sign-in key';
ALTER TABLE human_public_keys ADD COLUMN created BIGINT;
UPDATE human_public_keys SET key_id=md5(encode(public_key,'hex'));
ALTER TABLE human_public_keys DROP CONSTRAINT human_public_keys_pkey;
ALTER TABLE human_public_keys ADD PRIMARY KEY (key_id);
CREATE INDEX human_keys_account ON human_public_keys(account_id);
