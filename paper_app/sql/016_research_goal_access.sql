ALTER TABLE research_goals ADD COLUMN audience TEXT NOT NULL DEFAULT 'inherit'
    CHECK (audience IN ('inherit','owner','users','local','all','ai'));

ALTER TABLE item_grants DROP CONSTRAINT item_grants_kind_check;
ALTER TABLE item_grants ADD CHECK (kind IN ('paper','document','comment','skill','research_goal'));
