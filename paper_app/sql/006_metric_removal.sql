ALTER TABLE metric_corrections ADD COLUMN removed INTEGER NOT NULL DEFAULT 0 CHECK (removed IN (0,1));
