CREATE TABLE git_repository_state (
    kind TEXT NOT NULL CHECK(kind IN ('documents','experiments')),
    resource_id BIGINT NOT NULL,
    base_revision BIGINT NOT NULL,
    head TEXT NOT NULL,
    pack BYTEA NOT NULL,
    PRIMARY KEY(kind,resource_id)
);
