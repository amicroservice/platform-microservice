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

from typing import Any, Optional

import asyncpg
from db.pool import Database
from utils.logger import Logger


class AdminInviteTable:
    """Database access layer for the `admin_invites` table."""

    def __init__(self, logger: Logger, database: Database):
        self.logger = logger
        self.database = database

    def ready(self):
        if not self.database.pool:
            self.logger.critical("Not connected to the database.")
            return None

    async def get_valid_by_email(self, email: str) -> Optional[dict[str, Any]]:
        """Return the first unused invite for `email` or None."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    SELECT id, created_at, email, inviter_id, is_used, platform_id
                    FROM admin_invites
                    WHERE lower(email) = lower($1) AND is_used = false
                    LIMIT 1
                    """,
                    email,
                )

                if not record:
                    return None

                return {
                    "id": record["id"],
                    "created_at": record["created_at"],
                    "email": record["email"],
                    "inviter_id": record["inviter_id"],
                    "is_used": record["is_used"],
                    "platform_id": record["platform_id"],
                }

        except asyncpg.PostgresError as e:
            self.logger.error(
                f"{__name__}: Error retrieving invite by email {email} - {e}"
            )
            raise e

    async def mark_used(self, id: str) -> bool:
        """Mark an invite record as used. Returns True if an update occurred."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    record = await connection.fetchrow(
                        """
                        UPDATE admin_invites
                        SET is_used = true
                        WHERE id = $1
                        RETURNING id
                        """,
                        id,
                    )

                    return bool(record)

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error marking invite used {id} - {e}")
            raise e

    async def create(
        self, email: str, inviter_id: Optional[str], platform_id: Optional[str]
    ) -> Optional[str]:
        """Create an invite record and return its id."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    INSERT INTO admin_invites (email, inviter_id, platform_id)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    email,
                    inviter_id,
                    platform_id,
                )

                if not record:
                    return None

                return record["id"]

        except asyncpg.PostgresError as e:
            self.logger.error(
                f"{__name__}: Error creating invite for email {email} - {e}"
            )
            raise e
