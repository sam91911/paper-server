ALTER TABLE human_invites ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('member','user'));
