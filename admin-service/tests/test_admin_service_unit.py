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

import bcrypt
import jwt as pyjwt
import pytest
from google.rpc import code_pb2

import app.proto.admin_pb2 as admin_pb2
from app.services.admin import AdminService
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


class DummyAdminTable:
    def __init__(self):
        self.database = type("DB", (), {"pool": True})()
        self.records = []

    async def create(self, admin_create):
        class Rec:
            pass

        r = Rec()
        r.id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)
        r.created_at = now
        r.updated_at = now
        r.email = admin_create.email
        r.first_name = admin_create.first_name
        r.last_name = admin_create.last_name
        r.properties = admin_create.properties or {}
        r.is_active = admin_create.is_active
        r.is_superadmin = admin_create.is_superadmin
        r.platform_id = admin_create.platform_id
        r.password_hash = bcrypt.hashpw(
            admin_create.password.encode("utf-8"), bcrypt.gensalt()
        )
        self.records.append(r)
        return r

    async def get_by_email(self, email):
        for r in self.records:
            if r.email.lower() == email.lower():
                return r
        return None

    async def get_by_email_and_platform(self, email, platform_id):
        for r in self.records:
            if r.email.lower() == email.lower() and r.platform_id == platform_id:
                return r
        return None

    async def get(self, id):
        for r in self.records:
            if str(r.id) == str(id):

                class Rec:
                    pass

                rr = Rec()
                rr.id = r.id
                rr.created_at = r.created_at
                rr.updated_at = r.updated_at
                rr.email = r.email
                rr.first_name = r.first_name
                rr.last_name = r.last_name
                rr.properties = r.properties or {}
                rr.is_active = r.is_active
                rr.is_superadmin = r.is_superadmin
                rr.platform_id = r.platform_id
                return rr
        return None

    async def update(self, id, admin_update):
        for r in self.records:
            if str(r.id) == str(id):
                if getattr(admin_update, "email", None) is not None:
                    r.email = admin_update.email
                if getattr(admin_update, "password", None) is not None:
                    r.password_hash = bcrypt.hashpw(
                        admin_update.password.encode("utf-8"), bcrypt.gensalt()
                    )
                if getattr(admin_update, "first_name", None) is not None:
                    r.first_name = admin_update.first_name
                if getattr(admin_update, "last_name", None) is not None:
                    r.last_name = admin_update.last_name
                if getattr(admin_update, "is_active", None) is not None:
                    r.is_active = admin_update.is_active
                if getattr(admin_update, "is_superadmin", None) is not None:
                    r.is_superadmin = admin_update.is_superadmin
                if getattr(admin_update, "platform_id", None) is not None:
                    r.platform_id = admin_update.platform_id
                if getattr(admin_update, "properties", None) is not None:
                    r.properties = admin_update.properties

                r.updated_at = datetime.datetime.now(datetime.timezone.utc)

                class Rec:
                    pass

                rr = Rec()
                rr.id = r.id
                rr.created_at = r.created_at
                rr.updated_at = r.updated_at
                rr.email = r.email
                rr.first_name = r.first_name
                rr.last_name = r.last_name
                rr.properties = r.properties or {}
                rr.is_active = r.is_active
                rr.is_superadmin = r.is_superadmin
                rr.platform_id = r.platform_id
                return rr

        return None

    async def list(
        self,
        order_by,
        limit,
        offset,
        filters=None,
        property_filters=None,
        property_in_filters=None,
    ):
        filters = filters or {}
        for r in self.records:
            # simple filter support for tests
            if "email" in filters:
                if r.email.lower() != filters["email"].lower():
                    continue
            if "platform_id" in filters:
                if r.platform_id is None or str(r.platform_id) != str(
                    filters["platform_id"]
                ):
                    continue

            class Rec:
                pass

            rr = Rec()
            rr.id = r.id
            rr.created_at = r.created_at
            rr.updated_at = r.updated_at
            rr.email = r.email
            rr.first_name = r.first_name
            rr.last_name = r.last_name
            rr.properties = r.properties or {}
            rr.is_active = r.is_active
            rr.is_superadmin = r.is_superadmin
            rr.platform_id = r.platform_id
            yield rr


def test_register_success():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="s",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    req = admin_pb2.RegisterRequest(
        email="super@example.com",
        password="P@ssw0rd1",
        password_confirm="P@ssw0rd1",
        first_name="Unit",
        last_name="Tester",
    )

    ctx = FakeContext()
    res = asyncio.run(srv.Register(req, ctx))
    assert res.WhichOneof("response") == "success"
    assert res.success.email == "super@example.com"


def test_login_missing_credentials():
    srv = AdminService(
        Logger("test"),
        DummyAdminTable(),
        jwt_secret="s",
        jwt_expiration_hours=24,
        super_admin_email=None,
    )
    req = admin_pb2.LoginRequest(email="", password="")
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Login(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.INVALID_ARGUMENT


def test_login_requires_platform_for_regular_admin():
    srv = AdminService(
        Logger("test"),
        DummyAdminTable(),
        jwt_secret="s",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )
    req = admin_pb2.LoginRequest(email="user@example.com", password="x")
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Login(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.INVALID_ARGUMENT


def test_login_invalid_password_and_success():
    table = DummyAdminTable()

    # create a regular admin with platform_id
    platform_id = uuid.uuid4()

    class CreateObj:
        pass

    co = CreateObj()
    co.email = "user@example.com"
    co.password = "P@ssw0rd1"
    co.password_confirm = "P@ssw0rd1"
    co.first_name = "U"
    co.last_name = "T"
    co.properties = {}
    co.platform_id = platform_id
    co.is_superadmin = False
    co.is_active = True

    # reuse table.create logic by creating via service
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="s",
        jwt_expiration_hours=24,
        super_admin_email=None,
    )
    # directly call table.create to add the record
    r = asyncio.run(table.create(co))

    # attempt login with wrong password
    req_bad = admin_pb2.LoginRequest(
        email="user@example.com", password="bad", platform_id=str(platform_id)
    )
    ctx_bad = FakeContext()
    with pytest.raises(AbortError):
        asyncio.run(srv.Login(req_bad, ctx_bad))
    assert ctx_bad.status is not None
    assert ctx_bad.status.code.value[0] == code_pb2.UNAUTHENTICATED

    # correct password
    req_good = admin_pb2.LoginRequest(
        email="user@example.com", password="P@ssw0rd1", platform_id=str(platform_id)
    )
    ctx_good = FakeContext()
    res = asyncio.run(srv.Login(req_good, ctx_good))
    assert res.WhichOneof("response") == "success"
    token = res.success.token
    assert token and isinstance(token, str)


def test_get_and_update_and_list():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="test-secret",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    # create an admin record
    class CreateObj:
        pass

    co = CreateObj()
    co.email = "owner@example.com"
    co.password = "P@ssw0rd1"
    co.password_confirm = "P@ssw0rd1"
    co.first_name = "Owner"
    co.last_name = "User"
    co.properties = {}
    co.platform_id = uuid.uuid4()
    co.is_superadmin = False
    co.is_active = True

    created = asyncio.run(table.create(co))

    # GET not found
    get_req = admin_pb2.GetRequest(id=str(uuid.uuid4()))
    res_not = asyncio.run(srv.Get(get_req, FakeContext()))
    assert res_not.WhichOneof("response") == "error"

    # GET found (requester must be authorized — owner or same-platform or superadmin)
    get_req2 = admin_pb2.GetRequest(id=str(created.id))
    payload_get = {"sub": str(created.id), "is_superadmin": False, "role": "admin"}
    token_get = pyjwt.encode(payload_get, "test-secret", algorithm="HS256")
    if isinstance(token_get, bytes):
        token_get = token_get.decode("utf-8")

    ctx_get = FakeContext(md=[("authorization", "Bearer " + token_get)])
    res_ok = asyncio.run(srv.Get(get_req2, ctx_get))
    assert res_ok.WhichOneof("response") == "success"
    assert res_ok.success.id == str(created.id)

    # UPDATE requires auth
    upd_req = admin_pb2.UpdateRequest(id=str(created.id), first_name="New")
    ctx = FakeContext()
    with pytest.raises(AbortError):
        asyncio.run(srv.Update(upd_req, ctx))
    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED

    # Update as owner
    payload = {"sub": str(created.id), "is_superadmin": False, "role": "admin"}
    token = pyjwt.encode(payload, "test-secret", algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    ctx_owner = FakeContext(md=[("authorization", "Bearer " + token)])
    res_upd = asyncio.run(srv.Update(upd_req, ctx_owner))
    assert res_upd.WhichOneof("response") == "success"
    assert res_upd.success.first_name == "New"

    # LIST requires superadmin token
    list_req = admin_pb2.ListRequest(limit=10, offset=0)
    # missing jwt config check (service has jwt) -> missing token
    ctx_list = FakeContext()
    with pytest.raises(AbortError):
        # List is an async generator; call a small collector
        async def collect_missing():
            async for _ in srv.List(list_req, ctx_list):
                pass

        asyncio.run(collect_missing())
    assert ctx_list.status is not None
    assert ctx_list.status.code.value[0] == code_pb2.UNAUTHENTICATED

    # List as superadmin
    payload2 = {"is_superadmin": True, "role": "superadmin"}
    token2 = pyjwt.encode(payload2, "test-secret", algorithm="HS256")
    if isinstance(token2, bytes):
        token2 = token2.decode("utf-8")

    ctx_super = FakeContext(md=[("authorization", "Bearer " + token2)])

    async def collect_ok():
        out = []
        async for a in srv.List(list_req, ctx_super):
            out.append(a)
        return out

    got = asyncio.run(collect_ok())
    assert any(g.email == "owner@example.com" for g in got)


def test_get_same_platform_and_superadmin():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="test-secret",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    class CreateObj:
        pass

    # Create admin A
    a = CreateObj()
    a.email = "a@example.com"
    a.password = "P@ssw0rd1"
    a.password_confirm = "P@ssw0rd1"
    a.first_name = "A"
    a.last_name = "User"
    a.properties = {}
    a.platform_id = uuid.uuid4()
    a.is_superadmin = False
    a.is_active = True
    created_a = asyncio.run(table.create(a))

    # Create admin B in same platform
    b = CreateObj()
    b.email = "b@example.com"
    b.password = "P@ssw0rd1"
    b.password_confirm = "P@ssw0rd1"
    b.first_name = "B"
    b.last_name = "User"
    b.properties = {}
    b.platform_id = created_a.platform_id
    b.is_superadmin = False
    b.is_active = True
    created_b = asyncio.run(table.create(b))

    # Create admin C in different platform
    c = CreateObj()
    c.email = "c@example.com"
    c.password = "P@ssw0rd1"
    c.password_confirm = "P@ssw0rd1"
    c.first_name = "C"
    c.last_name = "User"
    c.properties = {}
    c.platform_id = uuid.uuid4()
    c.is_superadmin = False
    c.is_active = True
    created_c = asyncio.run(table.create(c))

    # Token for admin A (non-superadmin) with platform_id
    payload_a = {
        "sub": str(created_a.id),
        "is_superadmin": False,
        "role": "admin",
        "platform_id": str(created_a.platform_id),
    }
    token_a = pyjwt.encode(payload_a, "test-secret", algorithm="HS256")
    if isinstance(token_a, bytes):
        token_a = token_a.decode("utf-8")

    ctx_a = FakeContext(md=[("authorization", "Bearer " + token_a)])

    # A should be able to get B (same platform)
    get_b = admin_pb2.GetRequest(id=str(created_b.id))
    res_b = asyncio.run(srv.Get(get_b, ctx_a))
    assert res_b.WhichOneof("response") == "success"

    # A should NOT be able to get C (different platform)
    get_c = admin_pb2.GetRequest(id=str(created_c.id))
    with pytest.raises(AbortError):
        asyncio.run(srv.Get(get_c, ctx_a))

    # Superadmin can get any admin
    payload_super = {"is_superadmin": True, "role": "superadmin"}
    token_super = pyjwt.encode(payload_super, "test-secret", algorithm="HS256")
    if isinstance(token_super, bytes):
        token_super = token_super.decode("utf-8")
    ctx_super = FakeContext(md=[("authorization", "Bearer " + token_super)])
    res_any = asyncio.run(srv.Get(get_c, ctx_super))
    assert res_any.WhichOneof("response") == "success"


def test_list_same_platform():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="test-secret",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    class CreateObj:
        pass

    # Create admin A
    a = CreateObj()
    a.email = "a_list@example.com"
    a.password = "P@ssw0rd1"
    a.password_confirm = "P@ssw0rd1"
    a.first_name = "A"
    a.last_name = "User"
    a.properties = {}
    a.platform_id = uuid.uuid4()
    a.is_superadmin = False
    a.is_active = True
    created_a = asyncio.run(table.create(a))

    # Create admin B in same platform
    b = CreateObj()
    b.email = "b_list@example.com"
    b.password = "P@ssw0rd1"
    b.password_confirm = "P@ssw0rd1"
    b.first_name = "B"
    b.last_name = "User"
    b.properties = {}
    b.platform_id = created_a.platform_id
    b.is_superadmin = False
    b.is_active = True
    created_b = asyncio.run(table.create(b))

    # Create admin C in different platform
    c = CreateObj()
    c.email = "c_list@example.com"
    c.password = "P@ssw0rd1"
    c.password_confirm = "P@ssw0rd1"
    c.first_name = "C"
    c.last_name = "User"
    c.properties = {}
    c.platform_id = uuid.uuid4()
    c.is_superadmin = False
    c.is_active = True
    created_c = asyncio.run(table.create(c))

    # Token for admin A (non-superadmin) with platform_id
    payload_a = {
        "sub": str(created_a.id),
        "is_superadmin": False,
        "role": "admin",
        "platform_id": str(created_a.platform_id),
    }
    token_a = pyjwt.encode(payload_a, "test-secret", algorithm="HS256")
    if isinstance(token_a, bytes):
        token_a = token_a.decode("utf-8")

    ctx_a = FakeContext(md=[("authorization", "Bearer " + token_a)])

    list_req = admin_pb2.ListRequest(limit=10, offset=0)

    async def collect():
        out = []
        async for adm in srv.List(list_req, ctx_a):
            out.append(adm)
        return out

    got = asyncio.run(collect())
    assert any(a.email == "a_list@example.com" for a in got)
    assert all(a.platform_id == str(created_a.platform_id) for a in got)


def test_update_owner_cannot_change_flags():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="test-secret",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    class CreateObj:
        pass

    co = CreateObj()
    co.email = "owner2@example.com"
    co.password = "P@ssw0rd1"
    co.password_confirm = "P@ssw0rd1"
    co.first_name = "Owner2"
    co.last_name = "User"
    co.properties = {}
    co.platform_id = uuid.uuid4()
    co.is_superadmin = False
    co.is_active = True

    created = asyncio.run(table.create(co))

    # Owner token
    payload = {"sub": str(created.id), "is_superadmin": False, "role": "admin"}
    token = pyjwt.encode(payload, "test-secret", algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    ctx_owner = FakeContext(md=[("authorization", "Bearer " + token)])

    # Owner tries to escalate to superadmin
    upd_req = admin_pb2.UpdateRequest(id=str(created.id), is_superadmin=True)
    with pytest.raises(AbortError):
        asyncio.run(srv.Update(upd_req, ctx_owner))


def test_update_superadmin_can_change_flags():
    table = DummyAdminTable()
    srv = AdminService(
        Logger("test"),
        table,
        jwt_secret="test-secret",
        jwt_expiration_hours=24,
        super_admin_email="super@example.com",
    )

    class CreateObj:
        pass

    co = CreateObj()
    co.email = "target@example.com"
    co.password = "P@ssw0rd1"
    co.password_confirm = "P@ssw0rd1"
    co.first_name = "Target"
    co.last_name = "User"
    co.properties = {}
    co.platform_id = uuid.uuid4()
    co.is_superadmin = False
    co.is_active = True

    created = asyncio.run(table.create(co))

    payload = {"is_superadmin": True, "role": "superadmin"}
    token = pyjwt.encode(payload, "test-secret", algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    ctx_super = FakeContext(md=[("authorization", "Bearer " + token)])

    # Superadmin can set is_superadmin
    upd_req = admin_pb2.UpdateRequest(id=str(created.id), is_superadmin=True)
    res = asyncio.run(srv.Update(upd_req, ctx_super))
    assert res.WhichOneof("response") == "success"
    assert res.success.is_superadmin is True

    # and can change is_active
    upd_req2 = admin_pb2.UpdateRequest(id=str(created.id), is_active=False)
    res2 = asyncio.run(srv.Update(upd_req2, ctx_super))
    assert res2.WhichOneof("response") == "success"
    assert res2.success.is_active is False
