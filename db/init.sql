CREATE TABLE IF NOT EXISTS burns (
    id SERIAL PRIMARY KEY,
    burn_code VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    iso_path TEXT NOT NULL,
    dvd_device TEXT,
    dvd_standard VARCHAR(8) NOT NULL,
    albums JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    burned_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS burns_created_at_idx ON burns (created_at DESC);
