CREATE INDEX paper_metadata_due ON paper_metadata_checks(next_check,paper_id);
CREATE INDEX paper_metadata_unchecked ON papers(id)
WHERE (sha256 IS NOT NULL OR trim(doi)<>'')
  AND (trim(doi)='' OR trim(title)='' OR trim(authors)='' OR trim(year)='' OR trim(venue)='' OR trim(publisher)='');
