# Copyright 2024 Taufik Hidayat authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Create Admin Schema with Multi-Tenant Isolation Logic
"""

from yoyo import step

# This ensures the platforms table exists before we try to reference it
__depends__ = {"100000_create-platform-schema"}


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(r"""
        -- Ensure extension for gen_random_uuid() is available
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- =============================================
        -- ADMINS TABLE
        -- =============================================
        CREATE TABLE admins (
            -- Primary Identifier
            id UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            
            -- Audit Timestamps
            created_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),
            updated_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),

            -- Authentication & Profile
            email text NOT NULL,
            password_hash bytea NOT NULL,
            first_name text NOT NULL,
            last_name text NOT NULL,

            -- Status & Permissions
            is_active boolean NOT NULL DEFAULT TRUE,
            is_superadmin boolean NOT NULL DEFAULT FALSE,

            -- The Scoping Field:
            -- NULL for the Global Superadmin
            -- UUID for the Platform-specific Admin
            platform_id UUID REFERENCES platforms(id) ON DELETE CASCADE,

            -- Flexible storage for admin-specific settings
            properties JSONB DEFAULT '{}'::jsonb,  

            -- Email Format Validation
            CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),

            -- THE CORE LOGIC CONSTRAINT:
            -- If you are a Superadmin, you MUST NOT have a platform_id.
            -- If you are a regular admin, you MUST have a platform_id.
            CONSTRAINT admin_platform_consistency CHECK (
                (is_superadmin IS TRUE AND platform_id IS NULL)
                OR (is_superadmin IS FALSE AND platform_id IS NOT NULL)
            )
        );

        -- =============================================
        -- STRATEGIC INDEXING FOR ISOLATION
        -- =============================================

        -- 1. Global Unique Index for Superadmins
        -- Ensures one 'boss@system.com' can be the system landlord.
        CREATE UNIQUE INDEX idx_admins_email_superadmin_global 
        ON admins (lower(email)) 
        WHERE (is_superadmin IS TRUE);

        -- 2. Platform-Scoped Unique Index for Regular Admins
        -- This is what allows 'bob@email.com' to exist on Website A AND Website B
        -- as two completely different, unrelated accounts.
        CREATE UNIQUE INDEX idx_admins_email_platform_silo 
        ON admins (platform_id, lower(email)) 
        WHERE (is_superadmin IS FALSE);

        -- Performance optimization for platform-based lookups
        CREATE INDEX idx_admins_platform_id ON admins(platform_id);
        
        -- Performance optimization for logins (active check + email)
        CREATE INDEX idx_admins_active_login ON admins(is_active, lower(email));

        -- GIN Index for searching within JSONB properties
        CREATE INDEX idx_admins_properties_gin ON admins USING gin (properties);


        -- =============================================
        -- AUTOMATED TIMESTAMP TRIGGER
        -- =============================================
        CREATE OR REPLACE FUNCTION update_admins_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        CREATE TRIGGER trg_update_admins_updated_at
            BEFORE UPDATE ON admins
            FOR EACH ROW
            EXECUTE FUNCTION update_admins_updated_at();
        """)


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- Clean up in reverse order
        DROP TRIGGER IF EXISTS trg_update_admins_updated_at ON admins;
        DROP FUNCTION IF EXISTS update_admins_updated_at();
        DROP TABLE IF EXISTS admins;
        """
    )


steps = [step(apply_step, rollback_step)]
