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
from google.protobuf import any_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import code_pb2, status_pb2
from grpc_status import rpc_status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

import proto.user_pb2 as user_pb2
import proto.user_pb2_grpc as user_pb2_grpc
from db.models.user import UserCreate, UserUpdate
from db.tables.user import UserTable

tracer = trace.get_tracer(__name__)


class UserService(user_pb2_grpc.UserServiceServicer):
    """
    UserService implements the gRPC service for managing users, including registration and authentication.
    It interacts with the database through UserTable and handles input validation using Pydantic models.
    The service also provides detailed error handling and logging for better observability.
    """

    def __init__(
        self,
        logger: Logger,
        user_table: UserTable,
        jwt_secret: str,
        jwt_expiration_hours: int,
    ) -> None:
        super().__init__()

        self.logger = logger
        self.user_table = user_table
        self.jwt_secret = jwt_secret
        self.jwt_expiration_hours = jwt_expiration_hours

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
                user_pb2.FieldError(
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
                    user_pb2.FieldError(
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

        # Validate with Pydantic UserCreate model; capture and return validation errors with field-level details
        with tracer.start_as_current_span("UserService.Register.validate"):
            try:
                user_create = UserCreate(
                    email=request.email,
                    password=request.password,
                    password_confirm=getattr(request, "password_confirm", ""),
                    first_name=request.first_name,
                    last_name=request.last_name,
                    properties=properties,
                    platform_id=platform_id,
                )
            except ValidationError as e:
                details = []
                for err in e.errors():
                    field_name = ".".join(str(p) for p in err.get("loc", ()))
                    code = err.get("type", "invalid")
                    message = err.get("msg", "")
                    detail = any_pb2.Any()
                    detail.Pack(
                        user_pb2.FieldError(
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
        with tracer.start_as_current_span("UserService.Register.db_create") as db_span:
            try:
                new_user = await self.user_table.create(user_create)
            except asyncpg.UniqueViolationError as err:
                db_span.set_attribute("error", True)
                db_span.set_attribute("error.type", "UniqueViolationError")
                await self.duplicate_email(
                    email=request.email, context=context, err=err
                )

            # Attach user id to db span; mark db span OK when creation succeeded
            if new_user is not None:
                db_span.set_attribute("user.id", str(new_user.id))
                try:
                    db_span.set_status(Status(StatusCode.OK))
                except Exception:
                    pass
            else:
                db_span.set_attribute("user.id", "")

            if new_user is None:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message="Failed to create user",
                        )
                    )
                )

        # Build response User proto
        created_ts = Timestamp()
        updated_ts = Timestamp()

        created_dt = new_user.created_at
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
        created_ts.FromDatetime(created_dt)

        updated_dt = new_user.updated_at
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
        updated_ts.FromDatetime(updated_dt)

        props_struct = Struct()
        ParseDict(new_user.properties or {}, props_struct)

        user_proto = user_pb2.User(
            id=str(new_user.id),
            created_at=created_ts,
            updated_at=updated_ts,
            email=new_user.email,
            first_name=new_user.first_name,
            last_name=new_user.last_name,
            properties=props_struct,
            is_active=new_user.is_active,
            platform_id=str(new_user.platform_id) if new_user.platform_id else "",
        )

        # Ensure top-level span records user.id and marks operation as successful
        try:
            span.set_attribute("user.id", str(new_user.id))
            span.set_status(Status(StatusCode.OK))
        except Exception:
            pass

        return user_pb2.RegisterResponse(success=user_proto)

    async def Login(self, request, context):
        """
        Login User
        """
        with tracer.start_as_current_span("UserService.Login") as span:
            span.set_attribute("user.email", getattr(request, "email", ""))

            email = getattr(request, "email", "").strip()
            password = getattr(request, "password", "")

            if not email or not password:
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
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
                        user_pb2.FieldError(
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

            # Regular user login: require platform_id and fetch by email+platform
            if platform_id is None:
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
                        field="platform_id",
                        code="required",
                        message="platform_id is required for user login",
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
                user = await self.user_table.get_by_email_and_platform(
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

            if not user:
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
                        field="email",
                        code="not_found",
                        message="User not found",
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

            if not user.is_active:
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
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
                    password.encode("utf-8"), user.password_hash
                )
            except Exception:
                password_matches = False

            if not password_matches:
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
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
                "sub": str(user.id),
                "email": user.email,
                "platform_id": str(user.platform_id) if user.platform_id else None,
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
                span.set_attribute("user.id", str(user.id))
                span.set_status(Status(StatusCode.OK))
            except Exception:
                pass

            return user_pb2.LoginResponse(success=user_pb2.UserToken(token=token))

    async def _require_superadmin(self, context):
        return await self._require_jwt_payload(context, require_superadmin=True)

    async def _require_jwt_payload(
        self,
        context,
        *,
        payload: dict | None = None,
        require_superadmin: bool = False,
        require_admin_or_superadmin: bool = False,
        allow_admin_token: bool = False,
        target_id: str | None = None,
        target_platform: str | None = None,
        allow_same_platform: bool = False,
    ):
        """Decode JWT payload and optionally enforce authorization rules.

        By default this only decodes and returns the token payload. When
        flags are provided the function will enforce the corresponding
        authorization checks and abort the RPC with an appropriate gRPC
        status on failure.
        """
        if not self.jwt_secret:
            detail = any_pb2.Any()
            detail.Pack(
                user_pb2.FieldError(
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

        # If a payload was provided by the caller, use it and skip decoding.
        if payload is None:
            # If a payload was provided by the caller, use it and skip decoding.
            if payload is None:
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
                        user_pb2.FieldError(
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
                        user_pb2.FieldError(
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
                        user_pb2.FieldError(
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
                        user_pb2.FieldError(
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

        # If caller asked specifically for superadmin privileges, enforce it here
        if require_superadmin:
            if not payload.get("is_superadmin"):
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
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

        # If caller requested the admin-or-superadmin checks, enforce them.
        if require_admin_or_superadmin:
            # Validate role claim when present
            role = payload.get("role")
            if role is not None and role not in ("admin", "superadmin"):
                detail = any_pb2.Any()
                detail.Pack(
                    user_pb2.FieldError(
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

            # Allow admin tokens when explicitly permitted and there are no target constraints
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

            # Otherwise forbidden
            detail = any_pb2.Any()
            detail.Pack(
                user_pb2.FieldError(
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

        return payload

    async def _require_admin_or_superadmin(
        self,
        context,
        target_id: str | None = None,
        target_platform: str | None = None,
        allow_same_platform: bool = False,
        allow_admin_token: bool = False,
        payload: dict | None = None,
    ):
        return await self._require_jwt_payload(
            context,
            payload=payload,
            require_admin_or_superadmin=True,
            allow_admin_token=allow_admin_token,
            target_id=target_id,
            target_platform=target_platform,
            allow_same_platform=allow_same_platform,
        )

    async def Get(self, request, context):
        with tracer.start_as_current_span("AdminService.Get"):
            # Require authentication and decode JWT once; always pass payload to authorizer.
            payload = await self._require_jwt_payload(context)
            target_id = getattr(request, "id", "") or str(payload.get("sub"))

            # Fetch target user; if not found, return not found
            user = await self.user_table.get(target_id)
            if not user:
                field_err = user_pb2.FieldError(
                    field="id", code="not_found", message="User not found"
                )
                val_err = user_pb2.ValidationError(
                    field_errors=[field_err], message="Not found"
                )
                return user_pb2.GetResponse(error=val_err)

            # Authorize via helper: allow superadmin, owner, or same-platform admin
            await self._require_admin_or_superadmin(
                context,
                target_id=target_id,
                target_platform=(str(user.platform_id) if user.platform_id else None),
                allow_same_platform=True,
                allow_admin_token=True,
                payload=payload,
            )

            created_ts = Timestamp()
            updated_ts = Timestamp()

            created_dt = user.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            updated_dt = user.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
            updated_ts.FromDatetime(updated_dt)

            props_struct = Struct()
            ParseDict(user.properties or {}, props_struct)

            user_proto = user_pb2.User(
                id=str(user.id),
                created_at=created_ts,
                updated_at=updated_ts,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                properties=props_struct,
                is_active=user.is_active,
                platform_id=str(user.platform_id) if user.platform_id else "",
            )

            return user_pb2.GetResponse(success=user_proto)

    async def Update(self, request, context):
        with tracer.start_as_current_span("UserService.Update") as span:
            # Decode JWT once and reuse payload for authorization. Request.id overrides token subject when provided.
            payload = await self._require_jwt_payload(context)
            target_id = getattr(request, "id", "") or str(payload.get("sub"))

            # Fetch target user
            target_user = await self.user_table.get(target_id)
            if not target_user:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.NOT_FOUND, message="User not found"
                        )
                    )
                )

            # Authorize caller: owner, same-platform admin, or superadmin (reuse decoded payload)
            payload = await self._require_admin_or_superadmin(
                context,
                target_id,
                target_platform=(
                    str(target_user.platform_id) if target_user.platform_id else None
                ),
                allow_same_platform=True,
                payload=payload,
            )

            # Determine caller identity and role
            caller_sub = (
                str(payload.get("sub")) if payload.get("sub") is not None else None
            )
            caller_role = payload.get("role")
            caller_is_superadmin = payload.get("is_superadmin")
            caller_is_owner = caller_sub and str(caller_sub) == str(target_id)

            # Field presence checks
            has_email = request.HasField("email")
            has_password = request.HasField("password")
            has_first_name = request.HasField("first_name")
            has_last_name = request.HasField("last_name")
            has_is_active = request.HasField("is_active")

            # Only superadmin may change is_active on behalf of others; owners cannot change their own is_active
            if caller_is_owner:
                if has_is_active:
                    detail = any_pb2.Any()
                    detail.Pack(
                        user_pb2.FieldError(
                            field="is_active",
                            code="forbidden",
                            message="Owners cannot change is_active",
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
                # Non-owner must be an admin or superadmin
                if not caller_is_superadmin and caller_role != "admin":
                    detail = any_pb2.Any()
                    detail.Pack(
                        user_pb2.FieldError(
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

                # Admins (non-superadmin) may only change `is_active`
                if caller_role == "admin" and not caller_is_superadmin:
                    other_changes = (
                        has_email or has_password or has_first_name or has_last_name
                    )
                    if other_changes:
                        detail = any_pb2.Any()
                        detail.Pack(
                            user_pb2.FieldError(
                                field="authorization",
                                code="forbidden",
                                message="Admin may only change is_active",
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

            # If password provided, require matching password_confirm
            if has_password:
                if (
                    not request.HasField("password_confirm")
                    or request.password_confirm != request.password
                ):
                    detail = any_pb2.Any()
                    detail.Pack(
                        user_pb2.FieldError(
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
                user_update = UserUpdate(
                    email=request.email if has_email else None,
                    password=request.password if has_password else None,
                    first_name=request.first_name if has_first_name else None,
                    last_name=request.last_name if has_last_name else None,
                    is_active=request.is_active if has_is_active else None,
                )
            except ValidationError as e:
                details = []
                for err in e.errors():
                    field_name = ".".join(str(p) for p in err.get("loc", ()))
                    code = err.get("type", "invalid")
                    message = err.get("msg", "")
                    detail = any_pb2.Any()
                    detail.Pack(
                        user_pb2.FieldError(
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

            updated = await self.user_table.update(target_id, user_update)
            if not updated:
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.NOT_FOUND,
                            message="User not found",
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

            user_proto = user_pb2.User(
                id=str(updated.id),
                created_at=created_ts,
                updated_at=updated_ts,
                email=updated.email,
                first_name=updated.first_name,
                last_name=updated.last_name,
                properties=props_struct,
                is_active=updated.is_active,
                platform_id=str(updated.platform_id) if updated.platform_id else "",
            )

            try:
                span.set_attribute("user.id", str(updated.id))
                span.set_status(Status(StatusCode.OK))
            except Exception:
                pass

            return user_pb2.UpdateResponse(success=user_proto)

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
                            user_pb2.FieldError(
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
                            user_pb2.FieldError(
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

            async for user in self.user_table.list(
                order_by, limit, offset, filters, property_filters, property_in_filters
            ):
                created_ts = Timestamp()
                updated_ts = Timestamp()

                created_dt = user.created_at
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                created_ts.FromDatetime(created_dt)

                updated_dt = user.updated_at
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
                updated_ts.FromDatetime(updated_dt)

                props_struct = Struct()
                ParseDict(user.properties or {}, props_struct)

                yield user_pb2.User(
                    id=str(user.id),
                    created_at=created_ts,
                    updated_at=updated_ts,
                    email=user.email,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    properties=props_struct,
                    is_active=user.is_active,
                    platform_id=str(user.platform_id) if user.platform_id else "",
                )
