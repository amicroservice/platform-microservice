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

import asyncio
import datetime
import uuid

import jwt as pyjwt
import pytest
from google.rpc import code_pb2

import app.proto.admin_invite_pb2 as invite_pb2
from app.services.admin_invite import AdminInviteService
from app.utils.logger import Logger


class AbortError(Exception):
    pass


class FakeContext:
    def __init__(self, md=None):
        self._md = md or []
        self.status = None

    def invocation_metadata(self):
        return self._md

    async def abort_with_status(self, status):
        self.status = status
        raise AbortError(status)


class DummyInviteTable:
    def __init__(self):
        self.database = type("DB", (), {"pool": True})()
        self.records = []

    async def create(self, *args, admin_invite_create=None, **kwargs):
        class Rec:
            pass

        r = Rec()
        r.id = uuid.uuid4()
        r.created_at = datetime.datetime.now(datetime.timezone.utc)
        # Support new signature: admin_invite_create (pydantic model)
        if admin_invite_create is not None:
            r.email = getattr(admin_invite_create, "email", "")
            inv = getattr(admin_invite_create, "inviter_id", None)
            r.inviter_id = str(inv) if inv is not None else None
            p = getattr(admin_invite_create, "platform_id", None)
            if p:
                try:
                    r.platform_id = uuid.UUID(str(p))
                except Exception:
                    r.platform_id = p
            else:
                r.platform_id = None
        else:
            # Backwards-compatible: create(email, inviter_id, platform_id)
            email = args[0] if len(args) >= 1 else kwargs.get("email", "")
            inviter_id = args[1] if len(args) >= 2 else kwargs.get("inviter_id", None)
            platform_id = args[2] if len(args) >= 3 else kwargs.get("platform_id", None)
            r.email = email
            r.inviter_id = str(inviter_id) if inviter_id is not None else None
            if platform_id:
                try:
                    r.platform_id = uuid.UUID(str(platform_id))
                except Exception:
                    r.platform_id = platform_id
            else:
                r.platform_id = None

        r.is_used = False
        self.records.append(r)
        return r

    async def get(self, id):
        for r in self.records:
            if str(r.id) == str(id):

                class Rec:
                    pass

                rec = Rec()
                rec.id = r.id
                rec.created_at = r.created_at
                rec.email = r.email
                rec.inviter_id = r.inviter_id
                rec.is_used = r.is_used
                rec.platform_id = r.platform_id
                return rec
        return None

    async def delete(self, id):
        for i, r in enumerate(self.records):
            if str(r.id) == str(id):
                popped = self.records.pop(i)

                class Rec:
                    pass

                rec = Rec()
                rec.id = popped.id
                rec.created_at = popped.created_at
                rec.email = popped.email
                rec.inviter_id = popped.inviter_id
                rec.is_used = popped.is_used
                rec.platform_id = popped.platform_id
                return rec
        return None

    async def list(self, order_by="created_at", limit=100, offset=0, filters=None):
        for r in self.records:
            if filters:
                if "email" in filters and filters.get("email"):
                    if r.email.lower() != filters.get("email").lower():
                        continue
                if "platform_id" in filters and filters.get("platform_id"):
                    if not r.platform_id or str(r.platform_id) != str(
                        filters.get("platform_id")
                    ):
                        continue

            class Rec:
                pass

            rec = Rec()
            rec.id = r.id
            rec.created_at = r.created_at
            rec.email = r.email
            rec.inviter_id = r.inviter_id
            rec.is_used = r.is_used
            rec.platform_id = r.platform_id
            yield rec


def make_token(payload, secret="test-secret"):
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def test_create_requires_superadmin():
    table = DummyInviteTable()
    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    req = invite_pb2.CreateRequest(
        email="invite@example.com", platform_id=str(uuid.uuid4())
    )
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Create(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED


def test_create_success_as_superadmin():
    table = DummyInviteTable()
    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    payload = {"sub": str(uuid.uuid4()), "is_superadmin": True, "role": "superadmin"}
    token = make_token(payload, "test-secret")

    md = [("authorization", "Bearer " + token)]
    ctx = FakeContext(md=md)

    req = invite_pb2.CreateRequest(
        email="invite@example.com", platform_id=str(uuid.uuid4())
    )
    res = asyncio.run(srv.Create(req, ctx))

    assert res.WhichOneof("response") == "success"
    assert res.success.email == "invite@example.com"


def test_get_requires_superadmin():
    table = DummyInviteTable()
    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    req = invite_pb2.GetRequest(id=str(uuid.uuid4()))
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Get(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED


def test_get_success_as_superadmin():
    table = DummyInviteTable()
    # seed one record
    rec = asyncio.run(table.create("get@example.com", None, str(uuid.uuid4())))

    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    payload = {"sub": str(uuid.uuid4()), "is_superadmin": True, "role": "superadmin"}
    token = make_token(payload, "test-secret")

    md = [("authorization", "Bearer " + token)]
    ctx = FakeContext(md=md)

    req = invite_pb2.GetRequest(id=str(rec.id))
    res = asyncio.run(srv.Get(req, ctx))

    assert res.WhichOneof("response") == "success"
    assert res.success.email == "get@example.com"


def test_list_success_as_superadmin():
    table = DummyInviteTable()
    asyncio.run(table.create("l1@example.com", None, str(uuid.uuid4())))
    asyncio.run(table.create("l2@example.com", None, str(uuid.uuid4())))

    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    payload = {"sub": str(uuid.uuid4()), "is_superadmin": True, "role": "superadmin"}
    token = make_token(payload, "test-secret")
    md = [("authorization", "Bearer " + token)]
    ctx = FakeContext(md=md)

    list_req = invite_pb2.ListRequest(limit=10, offset=0)

    async def collect():
        items = []
        async for it in srv.List(list_req, ctx):
            items.append(it)
        return items

    items = asyncio.run(collect())
    emails = {it.email for it in items}
    assert "l1@example.com" in emails and "l2@example.com" in emails


def test_delete_success_as_superadmin():
    table = DummyInviteTable()
    rec = asyncio.run(table.create("del@example.com", None, str(uuid.uuid4())))

    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    payload = {"sub": str(uuid.uuid4()), "is_superadmin": True, "role": "superadmin"}
    token = make_token(payload, "test-secret")
    md = [("authorization", "Bearer " + token)]
    ctx = FakeContext(md=md)

    del_req = invite_pb2.DeleteRequest(
        id=str(rec.id),
        platform_id=str(rec.platform_id) if rec.platform_id else str(uuid.uuid4()),
    )
    res = asyncio.run(srv.Delete(del_req, ctx))

    assert res.WhichOneof("response") == "success"
    assert res.success.email == "del@example.com"


def test_list_and_delete_require_superadmin():
    table = DummyInviteTable()
    # pre-populate one record
    rec = asyncio.run(table.create("a@b.com", None, str(uuid.uuid4())))
    iid = rec.id

    srv = AdminInviteService(Logger("test"), table, jwt_secret="test-secret")

    list_req = invite_pb2.ListRequest(limit=10, offset=0)
    ctx_list = FakeContext()
    with pytest.raises(AbortError):

        async def collect_missing():
            async for _ in srv.List(list_req, ctx_list):
                pass

        asyncio.run(collect_missing())

    assert ctx_list.status is not None
    assert ctx_list.status.code.value[0] == code_pb2.UNAUTHENTICATED

    del_req = invite_pb2.DeleteRequest(id=str(iid), platform_id=str(uuid.uuid4()))
    ctx_del = FakeContext()
    with pytest.raises(AbortError):
        asyncio.run(srv.Delete(del_req, ctx_del))

    assert ctx_del.status is not None
    assert ctx_del.status.code.value[0] == code_pb2.UNAUTHENTICATED
