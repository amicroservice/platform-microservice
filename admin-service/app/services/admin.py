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
import uuid
from logging import Logger

import asyncpg
import proto.admin_pb2 as admin_pb2
import proto.admin_pb2_grpc as admin_pb2_grpc
from db.models.admin import AdminCreate
from db.tables.admin import AdminTable
from db.tables.admin_invites import AdminInviteTable
from google.protobuf import any_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import code_pb2, status_pb2
from grpc_status import rpc_status
from opentelemetry import trace
from pydantic import ValidationError

tracer = trace.get_tracer(__name__)


class AdminService(admin_pb2_grpc.AdminServiceServicer):
    """
    AdminService implements the gRPC service for managing admin users, including registration and authentication.
    It interacts with the database through AdminTable and handles input validation using Pydantic models.
    The service also provides detailed error handling and logging for better observability.
    """

    def __init__(
        self,
        logger: Logger,
        admin_table: AdminTable,
        jwt_secret: str,
        super_admin_email: str,
    ) -> None:
        super().__init__()

        self.logger = logger
        self.admin_table = admin_table
        self.jwt_secret = jwt_secret
        self.super_admin_email = super_admin_email
        # Invite table helper
        self.invite_table = AdminInviteTable(
            logger=logger, database=admin_table.database
        )

    async def duplicate_email(
        self, email: str, context, err: asyncpg.UniqueViolationError
    ):
        # Detect unique-violation errors robustly and return an ALREADY_EXISTS status
        # Common asyncpg messages include 'duplicate key value violates unique constraint'
        err_str = str(err) if err is not None else ""
        constraint_name = getattr(err, "constraint_name", None)
        if (
            "duplicate key" in err_str
            or "violates unique constraint" in err_str
            or "unique constraint" in err_str
            or (constraint_name and "email" in str(constraint_name))
        ):
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
                    field="email",
                    code="already_exists",
                    message=f"Email {email} already exists",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.ALREADY_EXISTS,
                        message=f"Email {email} already exists",
                        details=[detail],
                    )
                )
            )

    async def Register(self, request, context):
        """
        Register
        """
        with tracer.start_as_current_span("AdminService.Register") as span:
            span.set_attribute("admin.email", getattr(request, "email", ""))
            return await self._register(request, context, span)

    async def _register(self, request, context, span):
        # Convert properties (google.protobuf.Struct) to plain dict
        properties = {}
        try:
            if request.HasField("properties"):
                properties = MessageToDict(request.properties)
        except Exception:
            # Fallback: try direct conversion
            try:
                properties = MessageToDict(request.properties)
            except Exception:
                properties = {}

        # Parse optional platform_id
        platform_id = None
        if getattr(request, "platform_id", ""):
            try:
                platform_id = uuid.UUID(request.platform_id)
            except Exception:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="platform_id",
                        code="invalid",
                        message="platform_id must be a valid UUID",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Invalid platform_id",
                            details=[detail],
                        )
                    )
                )

        # Determine whether this email is allowed to register.
        # If it matches the configured super admin email, permit superadmin registration.
        # Otherwise require an unused invite row for that email.
        is_superadmin = False
        invite_record = None
        email_value = getattr(request, "email", "").strip()

        if (
            self.super_admin_email
            and email_value.lower() == (self.super_admin_email or "").lower()
        ):
            is_superadmin = True
            platform_id = None
            span.set_attribute("admin.is_superadmin", True)
        else:
            with tracer.start_as_current_span(
                "AdminService.Register.invite_check"
            ) as invite_span:
                invite_span.set_attribute("admin.email", email_value)
                invite_record = await self.invite_table.get_valid_by_email(email_value)
                invite_span.set_attribute(
                    "admin.invite_found", invite_record is not None
                )
            if not invite_record:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="email",
                        code="forbidden",
                        message=f"Email {email_value} is not invited",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.PERMISSION_DENIED,
                            message="Registration forbidden",
                            details=[detail],
                        )
                    )
                )

        # Validate with Pydantic AdminCreate
        with tracer.start_as_current_span("AdminService.Register.validate"):
            try:
                admin_create = AdminCreate(
                    email=request.email,
                    password=request.password,
                    password_confirm=getattr(request, "password_confirm", ""),
                    first_name=request.first_name,
                    last_name=request.last_name,
                    properties=properties,
                    platform_id=platform_id,
                    is_superadmin=is_superadmin,
                )
            except ValidationError as e:
                details = []
                for err in e.errors():
                    field_name = ".".join(str(p) for p in err.get("loc", ()))
                    code = err.get("type", "invalid")
                    message = err.get("msg", "")
                    detail = any_pb2.Any()
                    detail.Pack(
                        admin_pb2.FieldError(
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

        # Persist to DB
        with tracer.start_as_current_span("AdminService.Register.db_create") as db_span:
            try:
                new_admin = await self.admin_table.create(admin_create)
            except asyncpg.UniqueViolationError as err:
                db_span.set_attribute("error", True)
                db_span.set_attribute("error.type", "UniqueViolationError")
                await self.duplicate_email(
                    email=request.email, context=context, err=err
                )
                return

            db_span.set_attribute("admin.id", str(new_admin.id) if new_admin else "")
            if new_admin is None:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message="Failed to create admin",
                        )
                    )
                )

        # If this registration used an invite, mark it consumed
        if invite_record:
            try:
                await self.invite_table.mark_used(str(invite_record["id"]))
            except Exception as e:
                self.logger.error(
                    f"{__name__}: Failed to mark invite used for {request.email} - {e}"
                )

        # Build response Admin proto
        created_ts = Timestamp()
        updated_ts = Timestamp()

        created_dt = new_admin.created_at
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
        created_ts.FromDatetime(created_dt)

        updated_dt = new_admin.updated_at
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
        updated_ts.FromDatetime(updated_dt)

        props_struct = Struct()
        ParseDict(new_admin.properties or {}, props_struct)

        admin_proto = admin_pb2.Admin(
            id=str(new_admin.id),
            created_at=created_ts,
            updated_at=updated_ts,
            email=new_admin.email,
            first_name=new_admin.first_name,
            last_name=new_admin.last_name,
            properties=props_struct,
            is_active=new_admin.is_active,
            is_superadmin=new_admin.is_superadmin,
            platform_id=str(new_admin.platform_id) if new_admin.platform_id else "",
        )

        return admin_pb2.RegisterResponse(success=admin_proto)
