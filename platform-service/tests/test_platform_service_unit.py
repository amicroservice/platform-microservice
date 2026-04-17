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

import app.proto.platform_pb2 as platform_pb2
from app.services.platform import PlatformService
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
        # record the status and raise to stop execution like real gRPC
        self.status = status
        raise AbortError(status)


class DummyTable:
    async def create(self, create):
        now = datetime.datetime.now(datetime.timezone.utc)

        class Rec:
            pass

        r = Rec()
        r.id = uuid.uuid4()
        r.name = create.name
        r.domain_name = create.domain_name
        r.properties = create.properties
        r.created_at = now
        r.updated_at = now
        return r


def test_create_requires_jwt_configured():
    srv = PlatformService(Logger("test"), DummyTable())
    req = platform_pb2.CreateRequest(name="Test", domain_name="example.com")
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Create(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.INTERNAL


def test_create_missing_token():
    srv = PlatformService(Logger("test"), DummyTable())
    srv.configure_jwt("test-secret")
    req = platform_pb2.CreateRequest(name="Test", domain_name="example.com")
    ctx = FakeContext()

    with pytest.raises(AbortError):
        asyncio.run(srv.Create(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED


def test_create_invalid_token():
    srv = PlatformService(Logger("test"), DummyTable())
    srv.configure_jwt("test-secret")
    req = platform_pb2.CreateRequest(name="Test", domain_name="example.com")
    ctx = FakeContext(md=[("authorization", "Bearer badtoken")])

    with pytest.raises(AbortError):
        asyncio.run(srv.Create(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED


def test_create_success():
    srv = PlatformService(Logger("test"), DummyTable())
    srv.configure_jwt("test-secret")

    payload = {"is_superadmin": True}
    token = pyjwt.encode(payload, "test-secret", algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    req = platform_pb2.CreateRequest(name="Test", domain_name="example.com")
    ctx = FakeContext(md=[("authorization", "Bearer " + token)])

    res = asyncio.run(srv.Create(req, ctx))

    assert res.WhichOneof("response") == "success"
    assert res.success.name == "Test"


def test_create_expired_token():
    srv = PlatformService(Logger("test"), DummyTable())
    srv.configure_jwt("test-secret")

    # Create a token with an expiry in the past
    import datetime as _dt

    past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
    exp = int(past.timestamp())
    token = pyjwt.encode(
        {"is_superadmin": True, "exp": exp}, "test-secret", algorithm="HS256"
    )
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    req = platform_pb2.CreateRequest(name="Test", domain_name="example.com")
    ctx = FakeContext(md=[("authorization", "Bearer " + token)])

    with pytest.raises(AbortError):
        asyncio.run(srv.Create(req, ctx))

    assert ctx.status is not None
    assert ctx.status.code.value[0] == code_pb2.UNAUTHENTICATED
