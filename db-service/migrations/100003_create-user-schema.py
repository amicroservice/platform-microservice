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
Create User Schema
"""

from yoyo import step

__depends__ = {"100002_create-admin--invite-schema"}


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(r"""
        -- Ensure extension for gen_random_uuid()
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- Users table to store user accounts
        CREATE TABLE users (
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

            -- Platform relation: users must belong to a platform
            platform_id UUID NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,

            -- User settings
            properties JSONB DEFAULT '{}'::jsonb,

            -- Constraints
            CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
        );

        -- =============================================
        -- Strategic Indexing for Optimal Performance
        -- =============================================

        -- Case-insensitive unique index for email (normalize with lower())
        CREATE UNIQUE INDEX idx_users_email_ci ON users (lower(email));

        -- Indexes for efficient querying
        CREATE INDEX idx_users_is_active ON users(is_active);

        -- Index for platform lookups
        CREATE INDEX idx_users_platform_id ON users(platform_id);
        
        -- JSONB Indexing for Flexible Properties
        CREATE INDEX idx_users_properties_gin ON users USING gin (properties);

        -- Composite Indexes for Common Query Patterns (use lower(email) to match ci-unique index)
        CREATE INDEX idx_users_active_email ON users(is_active, lower(email));

        -- =============================================
        -- Automated Timestamp Management
        -- =============================================

        -- Create updated_at trigger function
        CREATE OR REPLACE FUNCTION update_users_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        -- Apply trigger for automatic updated_at maintenance
        CREATE TRIGGER update_users_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION update_users_updated_at();
        """)


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        -- =============================================
        -- Revert users table creation
        -- Removes all associated objects in safe order
        -- =============================================

        -- Drop triggers first (depend on table)
        DROP TRIGGER IF EXISTS update_users_updated_at ON users;

        -- Drop function (used by trigger)
        DROP FUNCTION IF EXISTS update_users_updated_at();

        -- Drop indexes (depend on table)
        DROP INDEX IF EXISTS idx_users_active_email;
        DROP INDEX IF EXISTS idx_users_platform_id;
        DROP INDEX IF EXISTS idx_users_email_ci;
        DROP INDEX IF EXISTS idx_users_properties_gin;
        DROP INDEX IF EXISTS idx_users_is_active;

        -- Drop table last (base object)
        DROP TABLE IF EXISTS users;
        """
    )


steps = [step(apply_step, rollback_step)]
