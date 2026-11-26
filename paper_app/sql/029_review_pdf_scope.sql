ALTER TABLE review_requests ADD COLUMN end_page INTEGER;
ALTER TABLE review_requests ADD COLUMN whole_pdf INTEGER NOT NULL DEFAULT 0 CHECK (whole_pdf IN (0,1));
ALTER TABLE review_requests ADD COLUMN source_format TEXT NOT NULL DEFAULT 'pdf' CHECK (source_format IN ('pdf','text'));
