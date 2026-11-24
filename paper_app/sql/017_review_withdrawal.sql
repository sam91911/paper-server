ALTER TABLE review_requests DROP CONSTRAINT review_requests_status_check;
ALTER TABLE review_requests ADD CHECK (status IN ('pending','complete','failed','withdrawn'));
