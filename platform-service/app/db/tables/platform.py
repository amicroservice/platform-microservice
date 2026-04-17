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
from utils.logger import Logger

from db.models.platform import (
    PlatformCreate,
    PlatformInDB,
    PlatformRead,
    PlatformUpdate,
)
from db.pool import Database


class PlatformTable:
    """Database access layer for the `platforms` table."""

    def __init__(self, logger: Logger, database: Database):
        self.logger = logger
        self.database = database

    def ready(self):
        if not self.database.pool:
            self.logger.critical("Not connected to the database.")
            return None

    async def create(self, platform_create: PlatformCreate) -> Optional[PlatformInDB]:
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    props = platform_create.properties or {}
                    if not isinstance(props, str):
                        props_param = json.dumps(props)
                    else:
                        props_param = props

                    record = await connection.fetchrow(
                        """
                        INSERT INTO platforms (name, domain_name, properties)
                        VALUES ($1, $2, $3)
                        RETURNING id, created_at, updated_at, name, domain_name, properties
                        """,
                        platform_create.name,
                        platform_create.domain_name,
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

                    return PlatformInDB(
                        id=record["id"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                        name=record["name"],
                        domain_name=record["domain_name"],
                        properties=props or {},
                    )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error inserting platform record - {e}")
            raise e

    async def get(self, id: str) -> Optional[PlatformRead]:
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                record = await connection.fetchrow(
                    """
                    SELECT id, created_at, updated_at, name, domain_name, properties
                    FROM platforms
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

                return PlatformRead(
                    id=record["id"],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                    name=record["name"],
                    domain_name=record["domain_name"],
                    properties=props or {},
                )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error retrieving platform by ID {id} - {e}")
            raise e

    async def update(
        self, id: str, platform_update: PlatformUpdate
    ) -> Optional[PlatformRead]:
        self.ready()

        try:
            async with self.database.pool.acquire() as connection:
                async with connection.transaction():
                    set_clauses = []
                    values: list[Any] = []
                    idx = 1

                    if platform_update.name is not None:
                        set_clauses.append(f"name = ${idx}")
                        values.append(platform_update.name)
                        idx += 1

                    if platform_update.domain_name is not None:
                        set_clauses.append(f"domain_name = ${idx}")
                        values.append(platform_update.domain_name)
                        idx += 1

                    if platform_update.properties is not None:
                        set_clauses.append(f"properties = ${idx}")
                        props_val = platform_update.properties
                        if not isinstance(props_val, str):
                            props_val = json.dumps(props_val)
                        values.append(props_val)
                        idx += 1

                    if not set_clauses:
                        return await self.get(id)

                    set_clause = ", ".join(set_clauses) + ", updated_at = NOW()"
                    query = f"""
                        UPDATE platforms
                        SET {set_clause}
                        WHERE id = ${idx}
                        RETURNING id, created_at, updated_at, name, domain_name, properties
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

                    return PlatformRead(
                        id=record["id"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                        name=record["name"],
                        domain_name=record["domain_name"],
                        properties=props or {},
                    )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error updating platform {id} - {e}")
            raise e

    async def list(
        self,
        order_by: str,
        limit: int,
        offset: int,
        filters: Optional[dict[str, Any]] = None,
        property_filters: Optional[dict[str, Any]] = None,
        property_in_filters: Optional[dict[str, list[str]]] = None,
    ) -> AsyncIterator[PlatformRead]:
        allowed_fields = {"id", "created_at", "updated_at", "name", "domain_name"}

        filters = filters or {}
        property_filters = property_filters or {}
        property_in_filters = property_in_filters or {}

        if order_by not in allowed_fields and order_by != "properties":
            raise ValueError(f"Invalid order_by field: {order_by}")

        query = """
            SELECT id, created_at, updated_at, name, domain_name, properties
            FROM platforms
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

                        yield PlatformRead(
                            id=record["id"],
                            created_at=record["created_at"],
                            updated_at=record["updated_at"],
                            name=record["name"],
                            domain_name=record["domain_name"],
                            properties=props or {},
                        )

        except asyncpg.PostgresError as e:
            self.logger.error(f"{__name__}: Error listing platforms - {e}")
            raise e
