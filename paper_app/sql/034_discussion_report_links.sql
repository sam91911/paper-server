ALTER TABLE document_contexts ADD COLUMN report_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL DEFERRABLE;
