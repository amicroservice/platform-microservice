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
Create Admin Invite Schema
"""

from yoyo import step

__depends__ = {"100001_create-admin-schema"}


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(r"""
        -- Ensure extension for gen_random_uuid()
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- Admin invites table to store invitation records (email-only flow)
        CREATE TABLE admin_invites (
            id UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            created_at timestamp(0) with time zone NOT NULL DEFAULT NOW(),
            email text NOT NULL,
            inviter_id UUID REFERENCES admins(id) ON DELETE SET NULL,
            is_used boolean NOT NULL DEFAULT FALSE,
            platform_id UUID REFERENCES platforms(id) ON DELETE CASCADE,
            CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
        );

        -- Indexes
        CREATE UNIQUE INDEX idx_admin_invites_email_ci ON admin_invites (lower(email));
        CREATE INDEX idx_admin_invites_is_used ON admin_invites(is_used);
        CREATE INDEX idx_admin_invites_platform_id ON admin_invites(platform_id);
        CREATE INDEX idx_admin_invites_active_email ON admin_invites(is_used, lower(email));
        """)


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        DROP INDEX IF EXISTS idx_admin_invites_active_email;
        DROP INDEX IF EXISTS idx_admin_invites_platform_id;
        DROP INDEX IF EXISTS idx_admin_invites_email_ci;
        DROP INDEX IF EXISTS idx_admin_invites_is_used;
        DROP TABLE IF EXISTS admin_invites;
        """
    )


steps = [step(apply_step, rollback_step)]
