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

import json
from typing import Any, AsyncIterator, Optional

import asyncpg
import bcrypt
from utils.logger import Logger

from db.models.user import UserCreate, UserInDB, UserRead, UserUpdate
from db.pool import Database


class UserTable:
    """
    Database access layer for the `users` table.

    Implements register/login/get/update/list operations aligned with
    the migration in `db-service/migrations/100003_create-user-schema.py`.
    """

    def __init__(self, logger: Logger, database: Database):
        self.logger = logger
        self.database = database

    def ready(self):
        """Check that connection pool is available."""
        if not self.database.pool:
            self.logger.critical("Not connected to the database.")
            return None

    async def create(self, user_create: UserCreate) -> Optional[UserInDB]:
        """Insert a new user and return the created record (including hash)."""
        self.ready()

        try:
            password_hash = bcrypt.hashpw(
                user_create.password.encode("utf-8"), bcrypt.gensalt()
            )

            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    # Ensure properties is serialized to JSON string for DB
                    props = user_create.properties or {}
                    if not isinstance(props, str):
                        props_param = json.dumps(props)
                    else:
                        props_param = props

                    record = await connection.fetchrow(
                        """
                        INSERT INTO users
                            (email, password_hash, first_name, last_name, is_active, platform_id, properties)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING id, created_at, updated_at, email, first_name, last_name, is_active, platform_id, properties, password_hash
                        """,
                        user_create.email,
                        password_hash,
                        user_create.first_name,
                        user_create.last_name,
                        user_create.is_active,
                        user_create.platform_id,
                        props_param,
                    )

                    if not record:
                        return None

                    raw_props = record["properties"]
                    if raw_props is None:
                        props = {}
                    elif isinstance(raw_props, str):
                        try:
                            props = json.loads(raw_props)
                        except Exception:
                            props = {}
                    else:
                        props = raw_props

                    return UserInDB(
                        id=record["id"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                        email=record["email"],
                        first_name=record["first_name"],
                        last_name=record["last_name"],
                        properties=props or {},
                        is_active=record["is_active"],
                        platform_id=record["platform_id"],
                        password_hash=bytes(record["password_hash"]),
                    )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error inserting user record - {e}")
            raise e

    async def get(self, id: str) -> Optional[UserRead]:
        """Retrieve user by id (does not include password hash)."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    SELECT id, created_at, updated_at, email, first_name, last_name, is_active, platform_id, properties
                    FROM users
                    WHERE id = $1
                    LIMIT 1
                    """,
                    id,
                )

                if not record:
                    return None

                raw_props = record["properties"]
                if raw_props is None:
                    props = {}
                elif isinstance(raw_props, str):
                    try:
                        props = json.loads(raw_props)
                    except Exception:
                        props = {}
                else:
                    props = raw_props

                return UserRead(
                    id=record["id"],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                    email=record["email"],
                    first_name=record["first_name"],
                    last_name=record["last_name"],
                    properties=props or {},
                    is_active=record["is_active"],
                    platform_id=record["platform_id"],
                )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error retrieving user by ID {id} - {e}")
            raise e

    async def get_by_email_and_platform(
        self, email: str, platform_id
    ) -> Optional[UserInDB]:
        """Retrieve user by email scoped to a specific platform (includes password hash)."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    SELECT id, created_at, updated_at, email, first_name, last_name, is_active, platform_id, properties, password_hash
                    FROM users
                    WHERE lower(email) = lower($1) AND platform_id = $2
                    LIMIT 1
                    """,
                    email,
                    platform_id,
                )

                if not record:
                    return None

                raw_props = record["properties"]
                if raw_props is None:
                    props = {}
                elif isinstance(raw_props, str):
                    try:
                        props = json.loads(raw_props)
                    except Exception:
                        props = {}
                else:
                    props = raw_props

                return UserInDB(
                    id=record["id"],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                    email=record["email"],
                    first_name=record["first_name"],
                    last_name=record["last_name"],
                    properties=props or {},
                    is_active=record["is_active"],
                    platform_id=record["platform_id"],
                    password_hash=bytes(record["password_hash"]),
                )

        except asyncpg.PostgresError as e:
            self.logger.error(
                f"{__name__}: Error retrieving user by email {email} and platform {platform_id} - {e}"
            )
            raise e

    async def update(self, id: str, user_update: UserUpdate) -> Optional[UserRead]:
        """Apply partial updates to a user and return the updated record."""
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    set_clauses = []
                    values: list[Any] = []
                    idx = 1

                    if user_update.email is not None:
                        set_clauses.append(f"email = ${idx}")
                        values.append(user_update.email)
                        idx += 1

                    if user_update.password is not None:
                        password_hash = bcrypt.hashpw(
                            user_update.password.encode("utf-8"), bcrypt.gensalt()
                        )
                        set_clauses.append(f"password_hash = ${idx}")
                        values.append(password_hash)
                        idx += 1

                    if user_update.first_name is not None:
                        set_clauses.append(f"first_name = ${idx}")
                        values.append(user_update.first_name)
                        idx += 1

                    if user_update.last_name is not None:
                        set_clauses.append(f"last_name = ${idx}")
                        values.append(user_update.last_name)
                        idx += 1

                    if user_update.is_active is not None:
                        set_clauses.append(f"is_active = ${idx}")
                        values.append(user_update.is_active)
                        idx += 1

                    # user-level superadmin flag is not stored in users table

                    if user_update.platform_id is not None:
                        set_clauses.append(f"platform_id = ${idx}")
                        values.append(user_update.platform_id)
                        idx += 1

                    if user_update.properties is not None:
                        set_clauses.append(f"properties = ${idx}")
                        props_val = user_update.properties
                        if not isinstance(props_val, str):
                            props_val = json.dumps(props_val)
                        values.append(props_val)
                        idx += 1

                    if not set_clauses:
                        return await self.get(id)

                    set_clause = ", ".join(set_clauses) + ", updated_at = NOW()"
                    query = f"""
                        UPDATE users
                        SET {set_clause}
                        WHERE id = ${idx}
                        RETURNING id, created_at, updated_at, email, first_name, last_name, is_active, platform_id, properties
                    """
                    values.append(id)

                    record = await connection.fetchrow(query, *values)

                    if not record:
                        return None
                    raw_props = record["properties"]
                    if raw_props is None:
                        props = {}
                    elif isinstance(raw_props, str):
                        try:
                            props = json.loads(raw_props)
                        except Exception:
                            props = {}
                    else:
                        props = raw_props

                    return UserRead(
                        id=record["id"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                        email=record["email"],
                        first_name=record["first_name"],
                        last_name=record["last_name"],
                        properties=props or {},
                        is_active=record["is_active"],
                        platform_id=record["platform_id"],
                    )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error updating user {id} - {e}")
            raise e

    async def list(
        self,
        order_by: str,
        limit: int,
        offset: int,
        filters: Optional[dict[str, Any]] = None,
        property_filters: Optional[dict[str, Any]] = None,
        property_in_filters: Optional[dict[str, list[str]]] = None,
    ) -> AsyncIterator[UserRead]:
        """List users with optional filters and JSONB property filters."""
        allowed_fields = {
            "id",
            "created_at",
            "updated_at",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "platform_id",
        }

        filters = filters or {}
        property_filters = property_filters or {}
        property_in_filters = property_in_filters or {}

        if order_by not in allowed_fields and order_by != "properties":
            raise ValueError(f"Invalid order_by field: {order_by}")

        query = """
            SELECT
                id,
                created_at,
                updated_at,
                email,
                first_name,
                last_name,
                is_active,
                platform_id,
                properties
            FROM users
        """

        where_clauses: list[str] = []
        values: list[Any] = []
        param_idx = 1

        for field, value in filters.items():
            if field not in allowed_fields:
                raise ValueError(f"Invalid filter field: {field}")

            where_clauses.append(f"{field} = ${param_idx}")
            values.append(value)
            param_idx += 1

        for key, value in property_filters.items():
            where_clauses.append(f"properties ->> '{key}' = ${param_idx}")
            values.append(value)
            param_idx += 1

        for key, value_list in property_in_filters.items():
            where_clauses.append(f"properties ->> '{key}' = ANY(${param_idx}::text[])")
            values.append(value_list)
            param_idx += 1

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += f" ORDER BY {order_by} LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        values.extend([limit, offset])

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    async for record in connection.cursor(query, *values):
                        raw_props = record["properties"]
                        if raw_props is None:
                            props = {}
                        elif isinstance(raw_props, str):
                            try:
                                props = json.loads(raw_props)
                            except Exception:
                                props = {}
                        else:
                            props = raw_props

                        yield UserRead(
                            id=record["id"],
                            created_at=record["created_at"],
                            updated_at=record["updated_at"],
                            email=record["email"],
                            first_name=record["first_name"],
                            last_name=record["last_name"],
                            properties=props or {},
                            is_active=record["is_active"],
                            platform_id=record["platform_id"],
                        )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error listing users - {e}")
            raise e
