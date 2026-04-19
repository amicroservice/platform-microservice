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

from typing import AsyncIterator, Optional

import asyncpg
from utils.logger import Logger

from db.models.admin_invite import AdminInviteCreate, AdminInviteInDB, AdminInviteRead
from db.pool import Database


class AdminInviteTable:
    """Database access layer for the `admin_invites` table."""

    def __init__(self, logger: Logger, database: Database):
        self.logger = logger
        self.database = database

    def ready(self):
        if not self.database.pool:
            self.logger.critical("Not connected to the database.")
            return None

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

    async def get(self, id: str) -> Optional[AdminInviteRead]:
        """Return invite record by id or None."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    SELECT id, created_at, email, inviter_id, is_used, platform_id
                    FROM admin_invites
                    WHERE id = $1
                    LIMIT 1
                    """,
                    id,
                )

                if not record:
                    return None

                return AdminInviteRead(
                    id=record["id"],
                    created_at=record["created_at"],
                    email=record["email"],
                    inviter_id=record["inviter_id"],
                    is_used=record["is_used"],
                    platform_id=record["platform_id"],
                )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error retrieving invite {id} - {e}")
            raise e

    async def delete(self, id: str) -> Optional[AdminInviteRead]:
        """Delete an invite by id, returning the deleted row or None."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    record = await connection.fetchrow(
                        """
                        DELETE FROM admin_invites
                        WHERE id = $1
                        RETURNING id, created_at, email, inviter_id, is_used, platform_id
                        """,
                        id,
                    )

                    if not record:
                        return None

                    return AdminInviteRead(
                        id=record["id"],
                        created_at=record["created_at"],
                        email=record["email"],
                        inviter_id=record["inviter_id"],
                        is_used=record["is_used"],
                        platform_id=record["platform_id"],
                    )
        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error deleting invite {id} - {e}")
            raise e

    async def create(
        self, admin_invite_create: AdminInviteCreate
    ) -> Optional[AdminInviteInDB]:
        """Create an invite record and return its id."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    INSERT INTO admin_invites (email, inviter_id, platform_id)
                    VALUES ($1, $2, $3)
                    RETURNING id, created_at, email, inviter_id, is_used, platform_id
                    """,
                    admin_invite_create.email,
                    admin_invite_create.inviter_id,
                    admin_invite_create.platform_id,
                )

                if not record:
                    return None

                return AdminInviteInDB(
                    id=record["id"],
                    created_at=record["created_at"],
                    email=record["email"],
                    inviter_id=record["inviter_id"],
                    is_used=record["is_used"],
                    platform_id=record["platform_id"],
                )

        except asyncpg.PostgresError as e:
            self.logger.error(
                f"{__name__}: Error creating invite for email {admin_invite_create.email} - {e}"
            )
            raise e

    async def list(
        self,
        order_by: str = "created_at",
        limit: int = 100,
        offset: int = 0,
        filters: Optional[dict[str, str]] = None,
    ) -> AsyncIterator[AdminInviteRead]:
        """Async generator that yields invite records matching filters.

        Supported filters: email (case-insensitive), platform_id, is_used (true/false strings).
        """
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                where_clauses = []
                params: list = []
                idx = 1

                if filters:
                    email = filters.get("email")
                    if email:
                        where_clauses.append(f"lower(email) = lower(${idx})")
                        params.append(email)
                        idx += 1

                    platform_id = filters.get("platform_id")
                    if platform_id:
                        where_clauses.append(f"platform_id = ${idx}")
                        params.append(platform_id)
                        idx += 1

                    is_used = filters.get("is_used")
                    if is_used is not None:
                        val = str(is_used).lower() in ("1", "true", "t", "yes")
                        where_clauses.append(f"is_used = ${idx}")
                        params.append(val)
                        idx += 1

                where_sql = (
                    f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                )

                # Sanitize order_by (allow only a small set)
                if order_by not in ("created_at", "email", "is_used"):
                    order_by = "created_at"

                sql = f"""
                    SELECT id, created_at, email, inviter_id, is_used, platform_id
                    FROM admin_invites
                    {where_sql}
                    ORDER BY {order_by}
                    LIMIT ${idx} OFFSET ${idx+1}
                """

                params.append(limit)
                params.append(offset)

                records: list[asyncpg.Record] = await connection.fetch(sql, *params)

                for record in records:
                    yield AdminInviteRead(
                        id=record["id"],
                        created_at=record["created_at"],
                        email=record["email"],
                        inviter_id=record["inviter_id"],
                        is_used=record["is_used"],
                        platform_id=record["platform_id"],
                    )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error listing invites - {e}")
            raise e
