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

import datetime
from logging import Logger

import asyncpg
import jwt
from google.protobuf import any_pb2
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import code_pb2, status_pb2
from grpc_status import rpc_status
from opentelemetry import trace
from pydantic import ValidationError

import proto.platform_pb2 as platform_pb2
import proto.platform_pb2_grpc as platform_pb2_grpc
from db.models.platform import PlatformCreate, PlatformUpdate
from db.tables.platform import PlatformTable

tracer = trace.get_tracer(__name__)


class PlatformService(platform_pb2_grpc.PlatformServiceServicer):
    """gRPC service implementation for platform management."""

    def __init__(self, logger: Logger, platform_table: PlatformTable) -> None:
        super().__init__()
        self.logger = logger
        self.platform_table = platform_table
        self.jwt_secret: str | None = None

    def configure_jwt(self, jwt_secret: str | None):
        """Optional: provide JWT secret (from server env) for auth checks."""
        self.jwt_secret = jwt_secret

    async def _require_superadmin(self, context):
        # Ensure JWT secret is configured
        if not self.jwt_secret:
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="config",
                    message="JWT secret not configured on server",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.INTERNAL,
                        message="Server misconfigured",
                        details=[detail],
                    )
                )
            )

        # Extract token from metadata (authorization: Bearer <token>)
        token = None
        try:
            md = context.invocation_metadata() or []
            for k, v in md:
                if k.lower() == "authorization":
                    if isinstance(v, str) and v.lower().startswith("bearer "):
                        token = v[7:]
                    else:
                        token = v
                    break
        except Exception:
            token = None

        if not token:
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="required",
                    message="Authorization token required",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.UNAUTHENTICATED,
                        message="Missing authorization token",
                        details=[detail],
                    )
                )
            )

        # Decode and validate; handle expired and invalid tokens explicitly
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="expired",
                    message="Token expired",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.UNAUTHENTICATED,
                        message="Token expired",
                        details=[detail],
                    )
                )
            )
        except jwt.InvalidTokenError:
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="invalid",
                    message="Invalid token",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.UNAUTHENTICATED,
                        message="Invalid token",
                        details=[detail],
                    )
                )
            )
        except Exception:
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="invalid",
                    message="Invalid token",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.UNAUTHENTICATED,
                        message="Invalid token",
                        details=[detail],
                    )
                )
            )

        if not payload.get("is_superadmin"):
            detail = any_pb2.Any()
            detail.Pack(
                platform_pb2.FieldError(
                    field="authorization",
                    code="forbidden",
                    message="Superadmin privileges required",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.PERMISSION_DENIED,
                        message="Forbidden",
                        details=[detail],
                    )
                )
            )

        return payload

    async def Create(self, request, context):
        with tracer.start_as_current_span("PlatformService.Create"):
            await self._require_superadmin(context)
            props = {}
            try:
                if request.HasField("properties"):
                    props = {}
                    # Using ParseDict requires a dict
                    try:
                        props = dict(request.properties)
                    except Exception:
                        props = {}
            except Exception:
                props = {}

            try:
                platform_create = PlatformCreate(
                    name=request.name,
                    domain_name=request.domain_name,
                    properties=props,
                )
            except ValidationError as e:
                details = []
                for err in e.errors():
                    field_name = ".".join(str(p) for p in err.get("loc", ()))
                    code = err.get("type", "invalid")
                    message = err.get("msg", "")
                    detail = any_pb2.Any()
                    detail.Pack(
                        platform_pb2.FieldError(
                            field=field_name, code=code, message=message
                        )
                    )
                    details.append(detail)

                if details:
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Validation field is error",
                                details=details,
                            )
                        )
                    )

                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Validation error",
                        )
                    )
                )

            try:
                new_platform = await self.platform_table.create(platform_create)
            except asyncpg.UniqueViolationError as err:
                self.logger.error(
                    f"{__name__}: Unique violation creating platform - {err}"
                )
                detail = any_pb2.Any()
                detail.Pack(
                    platform_pb2.FieldError(
                        field="domain_name",
                        code="already_exists",
                        message=f"Domain name {platform_create.domain_name} already exists",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.ALREADY_EXISTS,
                            message=f"Domain name {platform_create.domain_name} already exists",
                            details=[detail],
                        )
                    )
                )
                return
            except asyncpg.PostgresError as err:
                self.logger.error(
                    f"{__name__}: Error inserting platform record - {err}"
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message="Database error",
                        )
                    )
                )
                return

            if new_platform is None:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message="Failed to create platform",
                        )
                    )
                )

            created_ts = Timestamp()
            updated_ts = Timestamp()

            created_dt = new_platform.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            updated_dt = new_platform.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
            updated_ts.FromDatetime(updated_dt)

            props_struct = Struct()
            ParseDict(new_platform.properties or {}, props_struct)

            platform_proto = platform_pb2.Platform(
                id=str(new_platform.id),
                created_at=created_ts,
                updated_at=updated_ts,
                name=new_platform.name,
                domain_name=new_platform.domain_name,
                properties=props_struct,
            )

            return platform_pb2.CreateResponse(success=platform_proto)

    async def Get(self, request, context):
        with tracer.start_as_current_span("PlatformService.Get"):
            platform = await self.platform_table.get(request.id)
            if not platform:
                field_err = platform_pb2.FieldError(
                    field="id", code="not_found", message="Platform not found"
                )
                val_err = platform_pb2.ValidationError(
                    field_errors=[field_err], message="Not found"
                )
                return platform_pb2.GetResponse(error=val_err)

            created_ts = Timestamp()
            updated_ts = Timestamp()

            created_dt = platform.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            updated_dt = platform.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
            updated_ts.FromDatetime(updated_dt)

            props_struct = Struct()
            ParseDict(platform.properties or {}, props_struct)

            platform_proto = platform_pb2.Platform(
                id=str(platform.id),
                created_at=created_ts,
                updated_at=updated_ts,
                name=platform.name,
                domain_name=platform.domain_name,
                properties=props_struct,
            )

            return platform_pb2.GetResponse(success=platform_proto)

    async def Update(self, request, context):
        with tracer.start_as_current_span("PlatformService.Update"):
            await self._require_superadmin(context)
            props = None
            try:
                if request.HasField("properties"):
                    try:
                        props = dict(request.properties)
                    except Exception:
                        props = None
            except Exception:
                props = None

            try:
                platform_update = PlatformUpdate(
                    name=request.name if request.name else None,
                    domain_name=request.domain_name if request.domain_name else None,
                    properties=props,
                )
            except ValidationError as e:
                details = []
                for err in e.errors():
                    field_name = ".".join(str(p) for p in err.get("loc", ()))
                    code = err.get("type", "invalid")
                    message = err.get("msg", "")
                    detail = any_pb2.Any()
                    detail.Pack(
                        platform_pb2.FieldError(
                            field=field_name, code=code, message=message
                        )
                    )
                    details.append(detail)

                if details:
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Validation field is error",
                                details=details,
                            )
                        )
                    )

                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Validation error",
                        )
                    )
                )

            updated = await self.platform_table.update(request.id, platform_update)
            if not updated:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.NOT_FOUND,
                            message="Platform not found",
                        )
                    )
                )

            created_ts = Timestamp()
            updated_ts = Timestamp()

            created_dt = updated.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            updated_dt = updated.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
            updated_ts.FromDatetime(updated_dt)

            props_struct = Struct()
            ParseDict(updated.properties or {}, props_struct)

            platform_proto = platform_pb2.Platform(
                id=str(updated.id),
                created_at=created_ts,
                updated_at=updated_ts,
                name=updated.name,
                domain_name=updated.domain_name,
                properties=props_struct,
            )

            return platform_pb2.UpdateResponse(success=platform_proto)

    async def List(self, request, context):
        with tracer.start_as_current_span("PlatformService.List"):
            order_by = request.order_by or "created_at"
            limit = request.limit or 100
            offset = request.offset or 0
            filters = dict(request.filters) if request.filters else {}

            async for platform in self.platform_table.list(
                order_by, limit, offset, filters
            ):
                created_ts = Timestamp()
                updated_ts = Timestamp()

                created_dt = platform.created_at
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                created_ts.FromDatetime(created_dt)

                updated_dt = platform.updated_at
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
                updated_ts.FromDatetime(updated_dt)

                props_struct = Struct()
                ParseDict(platform.properties or {}, props_struct)

                yield platform_pb2.Platform(
                    id=str(platform.id),
                    created_at=created_ts,
                    updated_at=updated_ts,
                    name=platform.name,
                    domain_name=platform.domain_name,
                    properties=props_struct,
                )
