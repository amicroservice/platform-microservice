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
from google.protobuf.timestamp_pb2 import Timestamp
from google.rpc import code_pb2, status_pb2
from grpc_status import rpc_status
from opentelemetry import trace
from pydantic import ValidationError

import proto.admin_invite_pb2 as admin_invite_pb2
import proto.admin_invite_pb2_grpc as admin_invite_pb2_grpc
from db.models.admin_invite import AdminInviteCreate
from db.tables.admin_invites import AdminInviteTable

tracer = trace.get_tracer(__name__)


class AdminInviteService(admin_invite_pb2_grpc.AdminInviteServiceServicer):
    """gRPC service for admin invites."""

    def __init__(
        self,
        logger: Logger,
        invite_table: AdminInviteTable,
        jwt_secret: str | None = None,
    ) -> None:
        super().__init__()
        self.logger = logger
        self.invite_table = invite_table
        self.jwt_secret = jwt_secret or ""

    async def _require_jwt_payload(self, context):
        # Extract authorization header from metadata
        try:
            metadata = dict((k.lower(), v) for k, v in context.invocation_metadata())
        except Exception:
            metadata = {}

        auth = metadata.get("authorization")
        if not auth:
            detail = any_pb2.Any()
            detail.Pack(
                admin_invite_pb2.FieldError(
                    field="authorization",
                    code="required",
                    message="Authorization header is required",
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

        if not auth.lower().startswith("bearer "):
            detail = any_pb2.Any()
            detail.Pack(
                admin_invite_pb2.FieldError(
                    field="authorization",
                    code="invalid",
                    message="Invalid authorization header",
                )
            )
            await context.abort_with_status(
                rpc_status.to_status(
                    status_pb2.Status(
                        code=code_pb2.UNAUTHENTICATED,
                        message="Invalid authorization",
                        details=[detail],
                    )
                )
            )

        token = auth.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            detail = any_pb2.Any()
            detail.Pack(
                admin_invite_pb2.FieldError(
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
                admin_invite_pb2.FieldError(
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
                admin_invite_pb2.FieldError(
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

        return payload

    async def _require_superadmin(self, context):
        # Decode and ensure the token belongs to a superadmin
        payload = await self._require_jwt_payload(context)

        if not payload or not payload.get("is_superadmin"):
            detail = any_pb2.Any()
            detail.Pack(
                admin_invite_pb2.FieldError(
                    field="authorization",
                    code="forbidden",
                    message="Operation requires superadmin token",
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
        """
        Create a new admin invite. Requires superadmin token.
        """
        with tracer.start_as_current_span("AdminInviteService.Create") as span:
            span.set_attribute("admin_invite.email", getattr(request, "email", ""))

            # Require a valid superadmin token and extract inviter id from it
            payload = await self._require_superadmin(context)
            inviter_id = str(payload.get("sub"))

            if not inviter_id:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_invite_pb2.FieldError(
                        field="authorization",
                        code="forbidden",
                        message="Operation requires superadmin token",
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

            with tracer.start_as_current_span(
                "AdminInviteService.Create.Validation"
            ) as validation_span:
                try:
                    admin_invite_create = AdminInviteCreate(
                        email=getattr(request, "email", ""),
                        inviter_id=inviter_id,
                        platform_id=getattr(request, "platform_id", ""),
                    )
                    validation_span.set_attribute("validation.success", True)
                except ValidationError as e:
                    details = []
                    for err in e.errors():
                        field_name = ".".join(str(p) for p in err.get("loc", ()))
                        code = err.get("type", "invalid")
                        message = err.get("msg", "")
                        detail = any_pb2.Any()
                        detail.Pack(
                            admin_invite_pb2.FieldError(
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

                    validation_span.set_attribute("validation.success", False)
                    validation_span.set_attribute("validation.error", str(e))

                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INVALID_ARGUMENT,
                                message="Validation error",
                            )
                        )
                    )

            with tracer.start_as_current_span(
                "AdminInviteService.Create.save_to_db"
            ) as validation_save_span:
                try:
                    new_admin_invite = await self.invite_table.create(
                        admin_invite_create=admin_invite_create
                    )
                    validation_save_span.set_attribute("db.save_success", True)
                except asyncpg.UniqueViolationError as err:
                    self.logger.error(f"{__name__}: Create DB error: {err}")

                    validation_save_span.set_attribute("db.save_success", False)
                    validation_save_span.set_attribute("db.save_error", str(err))

                    detail = any_pb2.Any()
                    detail.Pack(
                        admin_invite_pb2.FieldError(
                            field="email",
                            code="already_exists",
                            message=f"Email {admin_invite_create.email} already exists",
                        )
                    )
                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.ALREADY_EXISTS,
                                message=f"Email {admin_invite_create.email} is already exists",
                                details=[detail],
                            )
                        )
                    )
                except Exception as e:
                    self.logger.error(f"{__name__}: Create DB error: {e}")

                    validation_save_span.set_attribute("db.save_success", False)
                    validation_save_span.set_attribute("db.save_error", str(e))

                    await context.abort_with_status(
                        rpc_status.to_status(
                            status_pb2.Status(
                                code=code_pb2.INTERNAL,
                                message=f"Database error {e} occurred while creating invite for email {admin_invite_create.email}",
                            )
                        )
                    )

            created_ts = Timestamp()
            created_dt = datetime.datetime.now(datetime.timezone.utc)
            created_ts.FromDatetime(created_dt)

            invite = admin_invite_pb2.AdminInvite(
                id=str(new_admin_invite.id),
                created_at=created_ts,
                email=new_admin_invite.email,
                inviter_id=str(new_admin_invite.inviter_id),
                is_used=bool(new_admin_invite.is_used),
                platform_id=str(new_admin_invite.platform_id),
            )

            validation_save_span.set_attribute("admin_invite.save_success", True)
            validation_save_span.set_attribute(
                "admin_invite.email", new_admin_invite.email
            )
            validation_save_span.set_attribute(
                "admin_invite.id", str(new_admin_invite.id)
            )

            return admin_invite_pb2.CreateResponse(success=invite)

    async def Get(self, request, context):
        # Require superadmin token for all read operations
        with tracer.start_as_current_span("AdminInviteService.Get") as span:
            await self._require_superadmin(context)

            invite_id = getattr(request, "id", "").strip()
            if not invite_id:
                span.set_attribute("get.error", "Missing id")
                detail = any_pb2.Any()
                detail.Pack(
                    admin_invite_pb2.FieldError(
                        field="id", code="required", message="id is required"
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Missing id",
                            details=[detail],
                        )
                    )
                )

            try:
                record = await self.invite_table.get(invite_id)
            except Exception as e:
                self.logger.error(f"{__name__}: Get DB error: {e}")

                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message=f"Database error {e} occurred while retrieving invite with id {invite_id}",
                        )
                    )
                )

            if not record:
                span.set_attribute("get.error", "Invite not found")
                field_err = admin_invite_pb2.FieldError(
                    field="id", code="not_found", message="Invite not found"
                )
                val_err = admin_invite_pb2.ValidationError(
                    field_errors=[field_err], message="Not found"
                )
                return admin_invite_pb2.GetResponse(error=val_err)

            ts = Timestamp()
            dt = record.created_at
            ts.FromDatetime(
                dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
            )

            invite = admin_invite_pb2.AdminInvite(
                id=str(record.id),
                created_at=ts,
                email=record.email or "",
                inviter_id=str(record.inviter_id) if record.inviter_id else "",
                is_used=bool(record.is_used),
                platform_id=str(record.platform_id) if record.platform_id else "",
            )

            span.set_attribute("get.success", True)
            span.set_attribute("get.id", str(record.id))

            return admin_invite_pb2.GetResponse(success=invite)

    async def Delete(self, request, context):
        with tracer.start_as_current_span("AdminInviteService.Delete") as span:
            # Require superadmin token for delete operations
            await self._require_superadmin(context)

            invite_id = getattr(request, "id", "").strip()
            if not invite_id:
                detail = any_pb2.Any()
                detail.Pack(
                    admin_invite_pb2.FieldError(
                        field="id", code="required", message="id is required"
                    )
                )
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INVALID_ARGUMENT,
                            message="Missing id",
                            details=[detail],
                        )
                    )
                )

            try:
                deleted = await self.invite_table.delete(invite_id)
            except Exception as e:
                span.set_attribute(
                    "delete.error",
                    f"Database error {e} occurred while deleting invite with id {invite_id}",
                )
                self.logger.error(f"{__name__}: Delete DB error: {e}")
                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message=f"Database error {e} occurred while deleting invite with id {invite_id}",
                        )
                    )
                )

            if not deleted:
                field_err = admin_invite_pb2.FieldError(
                    field="id",
                    code="not_found",
                    message="Invite not found or platform mismatch",
                )
                val_err = admin_invite_pb2.ValidationError(
                    field_errors=[field_err], message="Not found"
                )
                span.set_attribute(
                    "delete.error", "Invite not found or platform mismatch"
                )
                return admin_invite_pb2.DeleteResponse(error=val_err)

            ts = Timestamp()
            ts = Timestamp()
            dt = deleted.created_at
            ts.FromDatetime(
                dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
            )

            invite = admin_invite_pb2.AdminInvite(
                id=str(deleted.id),
                created_at=ts,
                email=deleted.email or "",
                inviter_id=str(deleted.inviter_id) if deleted.inviter_id else "",
                is_used=bool(deleted.is_used),
                platform_id=str(deleted.platform_id) if deleted.platform_id else "",
            )

            span.set_attribute("delete.success", True)
            span.set_attribute("delete.id", str(deleted.id))

            return admin_invite_pb2.DeleteResponse(success=invite)

    async def List(self, request, context):
        with tracer.start_as_current_span("AdminInviteService.List") as span:
            # Require superadmin token for listing
            await self._require_superadmin(context)

            order_by = getattr(request, "order_by", "created_at") or "created_at"
            limit = getattr(request, "limit", 100) or 100
            offset = getattr(request, "offset", 0) or 0
            filters = dict(request.filters) if getattr(request, "filters", None) else {}

            try:
                async for record in self.invite_table.list(
                    order_by, limit, offset, filters
                ):
                    ts = Timestamp()
                    dt = record.created_at
                    ts.FromDatetime(dt)

                    yield admin_invite_pb2.AdminInvite(
                        id=str(record.id),
                        created_at=ts,
                        email=record.email,
                        inviter_id=str(record.inviter_id) if record.inviter_id else "",
                        is_used=bool(record.is_used),
                        platform_id=str(record.platform_id),
                    )

                span.set_attribute("list.success", True)
            except Exception as e:
                span.set_attribute(
                    "list.error",
                    f"Database error {e} occurred while listing invites",
                )
                self.logger.error(f"{__name__}: List DB error: {e}")

                await context.abort_with_status(
                    rpc_status.to_status(
                        status_pb2.Status(
                            code=code_pb2.INTERNAL,
                            message=f"Database error {e} occurred while listing invites",
                        )
                    )
                )
