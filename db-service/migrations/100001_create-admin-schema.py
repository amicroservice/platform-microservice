"""
Create Admin Schema
"""

from yoyo import step

__depends__ = {}


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- Ensure extension for gen_random_uuid()
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- Admins table to store administrator accounts
        CREATE TABLE admins (
            -- Core fields
            id UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            created_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),

            -- Authentication fields
            email text NOT NULL,
            password_hash bytea NOT NULL,

            -- Personal information fields  
            first_name text NOT NULL,
            last_name text NOT NULL,

            -- Status fields
            is_active boolean NOT NULL DEFAULT TRUE,
            is_superadmin boolean NOT NULL DEFAULT FALSE,

            -- Platform relation: regular admins belong to a platform; superadmins do not
            platform_id UUID REFERENCES platforms(id) ON DELETE CASCADE,

            -- Admin settings
            properties JSONB DEFAULT '{}'::jsonb,  

            -- Constraints
            CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
            CONSTRAINT admin_platform_consistency CHECK (
                (is_superadmin AND platform_id IS NULL)
                OR (NOT is_superadmin AND platform_id IS NOT NULL)
            )
        );

        -- =============================================
        -- Strategic Indexing for Optimal Performance
        -- =============================================

        -- Case-insensitive unique index for email (normalize with lower())
        CREATE UNIQUE INDEX idx_admins_email_ci ON admins (lower(email));

        -- Indexes for efficient querying
        CREATE INDEX idx_admins_is_active ON admins(is_active);

        -- Index for platform lookups
        CREATE INDEX idx_admins_platform_id ON admins(platform_id);
        
        -- JSONB Indexing for Flexible Properties
        CREATE INDEX idx_admins_properties_gin ON admins USING gin (properties);

        -- Composite Indexes for Common Query Patterns (use lower(email) to match ci-unique index)
        CREATE INDEX idx_admins_active_email ON admins(is_active, lower(email));

        -- =============================================
        -- Automated Timestamp Management
        -- =============================================

        -- Create updated_at trigger function
        CREATE OR REPLACE FUNCTION update_admins_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        -- Apply trigger for automatic updated_at maintenance
        CREATE TRIGGER update_admins_updated_at
            BEFORE UPDATE ON admins
            FOR EACH ROW
            EXECUTE FUNCTION update_admins_updated_at();
        """
    )


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- =============================================
        -- Revert admins table creation
        -- Removes all associated objects in safe order
        -- =============================================

        -- Drop triggers first (depend on table)
        DROP TRIGGER IF EXISTS update_admins_updated_at ON admins;

        -- Drop function (used by trigger)
        DROP FUNCTION IF EXISTS update_admins_updated_at();

        -- Drop indexes (depend on table)
        DROP INDEX IF EXISTS idx_admins_active_email;
        DROP INDEX IF EXISTS idx_admins_platform_id;
        DROP INDEX IF EXISTS idx_admins_email_ci;
        DROP INDEX IF EXISTS idx_admins_properties_gin;
        DROP INDEX IF EXISTS idx_admins_is_active;

        -- Drop table last (base object)
        DROP TABLE IF EXISTS admins;
        """
    )


steps = [step(apply_step, rollback_step)]
