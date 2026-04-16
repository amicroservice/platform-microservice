"""
Create Platform Schema
"""

from yoyo import step

__depends__ = {}


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- Ensure extension for gen_random_uuid()
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- Platforms table to store platform records
        CREATE TABLE platforms (
            -- Core fields
            id UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            created_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),

            -- Identification
            name text NOT NULL,
            domain_name text NOT NULL,

            -- Settings
            properties JSONB DEFAULT '{}'::jsonb,

            -- Constraints
            -- Allow typical domains or plain 'localhost' for local development
            CONSTRAINT valid_domain_name CHECK (domain_name ~* '^(localhost|[a-z0-9]+([\\-\\.]{1}[a-z0-9]+)*\\.[a-z]{2,})$')
        );

        -- Case-insensitive unique index for domain_name
        CREATE UNIQUE INDEX idx_platforms_domain_name_ci ON platforms (lower(domain_name));
        CREATE INDEX idx_platforms_name ON platforms(name);

        -- Trigger to maintain updated_at
        CREATE OR REPLACE FUNCTION update_platforms_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        CREATE TRIGGER update_platforms_updated_at
            BEFORE UPDATE ON platforms
            FOR EACH ROW
            EXECUTE FUNCTION update_platforms_updated_at();
        """
    )


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- Revert platforms table creation
        DROP TRIGGER IF EXISTS update_platforms_updated_at ON platforms;
        DROP FUNCTION IF EXISTS update_platforms_updated_at();

        DROP INDEX IF EXISTS idx_platforms_domain_name_ci;
        DROP INDEX IF EXISTS idx_platforms_name;

        DROP TABLE IF EXISTS platforms;
        """
    )


steps = [step(apply_step, rollback_step)]
