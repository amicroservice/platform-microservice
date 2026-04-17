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
import bcrypt
import jwt
import proto.admin_pb2 as admin_pb2
import proto.admin_pb2_grpc as admin_pb2_grpc
from db.models.admin import AdminCreate, AdminUpdate
from db.tables.admin import AdminTable
from db.tables.admin_invites import AdminInviteTable
from google.protobuf import any_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import code_pb2, status_pb2
from grpc_status import rpc_status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
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
        jwt_expiration_hours: int,
        super_admin_email: str,
    ) -> None:
        super().__init__()

        self.logger = logger
        self.admin_table = admin_table
        self.jwt_secret = jwt_secret
        self.jwt_expiration_hours = jwt_expiration_hours
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

            # Attach admin id to db span; mark db span OK when creation succeeded
            if new_admin is not None:
                db_span.set_attribute("admin.id", str(new_admin.id))
                try:
                    db_span.set_status(Status(StatusCode.OK))
                except Exception:
                    pass
            else:
                db_span.set_attribute("admin.id", "")

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

        # Ensure top-level span records admin.id and marks operation as successful
        try:
            span.set_attribute("admin.id", str(new_admin.id))
            span.set_status(Status(StatusCode.OK))
        except Exception:
            pass

        return admin_pb2.RegisterResponse(success=admin_proto)

    async def Login(self, request, context):
        """
        Login User
        """
        with tracer.start_as_current_span("AdminService.Login") as span:
            span.set_attribute("admin.email", getattr(request, "email", ""))

            email = getattr(request, "email", "").strip()
            password = getattr(request, "password", "")

            if not email or not password:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="credentials",
                        code="invalid",
                        message="Email and password are required",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Missing credentials",
                            details=[detail],
                        )
                    )
                )

            # Parse optional platform_id for scoped login
            platform_id = None
            platform_id_raw = getattr(request, "platform_id", "")
            if platform_id_raw:
                try:
                    platform_id = uuid.UUID(platform_id_raw)
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

            # Superadmin logins do not use platform_id
            if (
                self.super_admin_email
                and email.lower() == (self.super_admin_email or "").lower()
            ):
                if platform_id is not None:
                    detail = any_pb2.Any()
                    detail.Pack(
                        admin_pb2.FieldError(
                            field="platform_id",
                            code="invalid",
                            message="Superadmin login must not include platform_id",
                        )
                    )
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Invalid platform_id for superadmin",
                                details=[detail],
                            )
                        )
                    )

                try:
                    admin = await self.admin_table.get_by_email(email)
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INTERNAL,
                                message="Internal error",
                            )
                        )
                    )
            else:
                # Regular admin MUST provide platform_id to disambiguate
                if platform_id is None:
                    detail = any_pb2.Any()
                    detail.Pack(
                        admin_pb2.FieldError(
                            field="platform_id",
                            code="required",
                            message="platform_id is required for regular admin login",
                        )
                    )
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Missing platform_id",
                                details=[detail],
                            )
                        )
                    )

                try:
                    admin = await self.admin_table.get_by_email_and_platform(
                        email, platform_id
                    )
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INTERNAL,
                                message="Internal error",
                            )
                        )
                    )

            if not admin:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="email",
                        code="not_found",
                        message="Admin not found",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.UNAUTHENTICATED,
                            message="Invalid credentials",
                            details=[detail],
                        )
                    )
                )

            if not admin.is_active:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="email",
                        code="inactive",
                        message="Account is inactive",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.PERMISSION_DENIED,
                            message="Account inactive",
                            details=[detail],
                        )
                    )
                )

            # Verify password
            try:
                password_matches = bcrypt.checkpw(
                    password.encode("utf-8"), admin.password_hash
                )
            except Exception:
                password_matches = False

            if not password_matches:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="password",
                        code="invalid",
                        message="Invalid credentials",
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.UNAUTHENTICATED,
                            message="Invalid credentials",
                            details=[detail],
                        )
                    )
                )

            # Generate JWT (use timezone-aware UTC to avoid deprecation warnings)
            now = datetime.datetime.now(datetime.timezone.utc)
            exp = now + datetime.timedelta(hours=self.jwt_expiration_hours)
            payload = {
                "sub": str(admin.id),
                "email": admin.email,
                "is_superadmin": admin.is_superadmin,
                "role": "superadmin" if admin.is_superadmin else "admin",
                "platform_id": str(admin.platform_id) if admin.platform_id else None,
                "iat": int(now.timestamp()),
                "exp": int(exp.timestamp()),
            }

            try:
                token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
            except Exception as e:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e))
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message="Failed to generate token",
                        )
                    )
                )

            try:
                span.set_attribute("admin.id", str(admin.id))
                span.set_status(Status(StatusCode.OK))
            except Exception:
                pass

            return admin_pb2.LoginResponse(success=admin_pb2.AdminToken(token=token))

    async def _require_superadmin(self, context):
        # Ensure JWT secret is configured
        if not self.jwt_secret:
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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

        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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

    # _require_jwt_payload removed — use _require_admin_or_superadmin instead

    async def _require_admin_or_superadmin(
        self,
        context,
        target_id: str | None = None,
        target_platform: str | None = None,
        allow_same_platform: bool = False,
        allow_admin_token: bool = False,
    ):
        # Ensure JWT secret is configured
        if not self.jwt_secret:
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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

        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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
                admin_pb2.FieldError(
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

        # Validate role claim when present
        role = payload.get("role")
        if role is not None and role not in ("admin", "superadmin"):
            detail = any_pb2.Any()
            detail.Pack(
                admin_pb2.FieldError(
                    field="authorization",
                    code="forbidden",
                    message="Invalid role",
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

        # Allow if payload is superadmin
        if payload.get("is_superadmin"):
            return payload

        # Allow admin tokens when explicitly permitted, but only when this call
        # is being used to *retrieve* the JWT payload (no target constraints).
        # When `target_id` or `target_platform` are provided we must still
        # enforce ownership/platform checks.
        if (
            allow_admin_token
            and role == "admin"
            and not target_id
            and not target_platform
        ):
            return payload

        # Allow if subject matches target_id (resource owner)
        if target_id and str(payload.get("sub")) == str(target_id):
            return payload

        # Allow if platform matching is enabled and the payload's platform matches target
        if allow_same_platform and target_platform:
            payload_platform = payload.get("platform_id")
            if payload_platform and str(payload_platform) == str(target_platform):
                return payload

        detail = any_pb2.Any()
        detail.Pack(
            admin_pb2.FieldError(
                field="authorization",
                code="forbidden",
                message="Operation permitted only for resource owner, superadmin, or same-platform admin",
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

    async def Get(self, request, context):
        with tracer.start_as_current_span("AdminService.Get"):
            # Determine target id: use request.id when provided, otherwise use the
            # authenticated token `sub` claim. Treat empty string as omitted.
            target_id = getattr(request, "id", "") or None

            # If no id supplied, require a valid token and use its `sub` claim
            if not target_id:
                payload = await self._require_admin_or_superadmin(
                    context, allow_admin_token=True
                )
                target_id = str(payload.get("sub"))

            # Fetch target admin; if not found, return not found
            admin = await self.admin_table.get(target_id)
            if not admin:
                field_err = admin_pb2.FieldError(
                    field="id", code="not_found", message="Admin not found"
                )
                val_err = admin_pb2.ValidationError(
                    field_errors=[field_err], message="Not found"
                )
                return admin_pb2.GetResponse(error=val_err)

            # Authorize via helper: allow superadmin, owner, or same-platform admin
            await self._require_admin_or_superadmin(
                context,
                target_id=target_id,
                target_platform=(str(admin.platform_id) if admin.platform_id else None),
                allow_same_platform=True,
                allow_admin_token=True,
            )

            created_ts = Timestamp()
            updated_ts = Timestamp()

            created_dt = admin.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            updated_dt = admin.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
            updated_ts.FromDatetime(updated_dt)

            props_struct = Struct()
            ParseDict(admin.properties or {}, props_struct)

            admin_proto = admin_pb2.Admin(
                id=str(admin.id),
                created_at=created_ts,
                updated_at=updated_ts,
                email=admin.email,
                first_name=admin.first_name,
                last_name=admin.last_name,
                properties=props_struct,
                is_active=admin.is_active,
                is_superadmin=admin.is_superadmin,
                platform_id=str(admin.platform_id) if admin.platform_id else "",
            )

            return admin_pb2.GetResponse(success=admin_proto)

    async def Update(self, request, context):
        with tracer.start_as_current_span("AdminService.Update") as span:
            # Allow resource owner or superadmin; capture caller payload
            payload = await self._require_admin_or_superadmin(context, request.id)

            # Only superadmin may change sensitive flags
            if request.HasField("is_superadmin") and not payload.get("is_superadmin"):
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="is_superadmin",
                        code="forbidden",
                        message="Only superadmin can change is_superadmin",
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

            if request.HasField("is_active") and not payload.get("is_superadmin"):
                detail = any_pb2.Any()
                detail.Pack(
                    admin_pb2.FieldError(
                        field="is_active",
                        code="forbidden",
                        message="Only superadmin can change is_active",
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

            props = None
            try:
                if request.HasField("properties"):
                    props = MessageToDict(request.properties)
            except Exception:
                props = None

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

            # If password provided, require matching password_confirm
            if getattr(request, "password", ""):
                if getattr(request, "password_confirm", "") != request.password:
                    detail = any_pb2.Any()
                    detail.Pack(
                        admin_pb2.FieldError(
                            field="password_confirm",
                            code="invalid",
                            message="password_confirm must match password",
                        )
                    )
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Password confirmation mismatch",
                                details=[detail],
                            )
                        )
                    )

            try:
                admin_update = AdminUpdate(
                    email=request.email if request.email else None,
                    password=request.password if request.password else None,
                    first_name=request.first_name if request.first_name else None,
                    last_name=request.last_name if request.last_name else None,
                    is_superadmin=request.is_superadmin
                    if request.HasField("is_superadmin")
                    else None,
                    is_active=request.is_active
                    if request.HasField("is_active")
                    else None,
                    platform_id=platform_id if platform_id is not None else None,
                    properties=props if props is not None else None,
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

            updated = await self.admin_table.update(request.id, admin_update)
            if not updated:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.NOT_FOUND,
                            message="Admin not found",
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

            admin_proto = admin_pb2.Admin(
                id=str(updated.id),
                created_at=created_ts,
                updated_at=updated_ts,
                email=updated.email,
                first_name=updated.first_name,
                last_name=updated.last_name,
                properties=props_struct,
                is_active=updated.is_active,
                is_superadmin=updated.is_superadmin,
                platform_id=str(updated.platform_id) if updated.platform_id else "",
            )

            try:
                span.set_attribute("admin.id", str(updated.id))
                span.set_status(Status(StatusCode.OK))
            except Exception:
                pass

            return admin_pb2.UpdateResponse(success=admin_proto)

    async def List(self, request, context):
        with tracer.start_as_current_span("AdminService.List"):
            order_by = request.order_by or "created_at"
            limit = request.limit or 100
            offset = request.offset or 0
            filters = dict(request.filters) if request.filters else {}
            property_filters = (
                dict(request.property_filters) if request.property_filters else {}
            )

            property_in_filters = {}
            try:
                if request.property_in_filters:
                    for k, v in request.property_in_filters.items():
                        # v is a StringList message
                        property_in_filters[k] = list(v.values)
            except Exception:
                property_in_filters = {}

            # Authorization: only admin-issued tokens may access this endpoint.
            # - Superadmins may list all.
            # - Admins may list their own platform.
            payload = await self._require_admin_or_superadmin(
                context, allow_admin_token=True
            )

            # Allow superadmin tokens
            if payload.get("is_superadmin"):
                pass
            else:
                # Use platform_id from token payload to enforce listing scope
                payload_platform = payload.get("platform_id")

                # If caller provided a platform_id filter, ensure it matches token's platform
                if "platform_id" in filters and filters.get("platform_id"):
                    if not payload_platform or str(payload_platform) != str(
                        filters.get("platform_id")
                    ):
                        detail = any_pb2.Any()
                        detail.Pack(
                            admin_pb2.FieldError(
                                field="authorization",
                                code="forbidden",
                                message="Regular admin may only list their own platform",
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
                else:
                    # restrict listing to caller's platform
                    if not payload_platform:
                        detail = any_pb2.Any()
                        detail.Pack(
                            admin_pb2.FieldError(
                                field="authorization",
                                code="forbidden",
                                message="Regular admin must have platform_id to list admins",
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
                    filters["platform_id"] = str(payload_platform)

            async for admin in self.admin_table.list(
                order_by, limit, offset, filters, property_filters, property_in_filters
            ):
                created_ts = Timestamp()
                updated_ts = Timestamp()

                created_dt = admin.created_at
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                created_ts.FromDatetime(created_dt)

                updated_dt = admin.updated_at
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
                updated_ts.FromDatetime(updated_dt)

                props_struct = Struct()
                ParseDict(admin.properties or {}, props_struct)

                yield admin_pb2.Admin(
                    id=str(admin.id),
                    created_at=created_ts,
                    updated_at=updated_ts,
                    email=admin.email,
                    first_name=admin.first_name,
                    last_name=admin.last_name,
                    properties=props_struct,
                    is_active=admin.is_active,
                    is_superadmin=admin.is_superadmin,
                    platform_id=str(admin.platform_id) if admin.platform_id else "",
                )
