CREATE FUNCTION paper_matches(title text, authors text, doi text, venue text, path text, terms text[])
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT NOT EXISTS (
        SELECT 1 FROM unnest(terms) AS query(term)
        WHERE strpos(lower(concat_ws(' ', title, authors, doi, venue, regexp_replace(path, E'^.*[/\\\\]', ''))), term) = 0
    );
$$;

CREATE FUNCTION publication_year(raw text)
RETURNS double precision LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    value text := lower(regexp_replace(raw, '^[[:space:]]+|[[:space:]]+$', '', 'g'));
    base integer;
    year double precision := 0;
    character_index integer;
BEGIN
    IF value ~ '^0(x[0-9a-f]+|b[01]+|o[0-7]+)$' THEN
        base := CASE substr(value, 2, 1) WHEN 'x' THEN 16 WHEN 'b' THEN 2 ELSE 8 END;
        FOR character_index IN 3..length(value) LOOP
            year := year * base + strpos('0123456789abcdef', substr(value, character_index, 1)) - 1;
        END LOOP;
    ELSIF value ~ '^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)(e[+-]?[0-9]+)?$' THEN
        year := value::double precision;
    END IF;
    RETURN NULLIF(year, 0);
EXCEPTION WHEN numeric_value_out_of_range THEN
    RETURN NULL;
END;
$$;
