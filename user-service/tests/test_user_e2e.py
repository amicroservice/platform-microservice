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

import glob
import importlib.util
import os
import uuid

import grpc
import jwt as pyjwt
import psycopg2
import pytest
from yoyo import get_backend, read_migrations

import app.proto.user_pb2 as user_pb2
import app.proto.user_pb2_grpc as user_pb2_grpc
from app.db.pool import Database
from app.db.tables.user import UserTable
from app.services.user import UserService
from app.utils.logger import Logger

# Locate migrations directory relative to this test file
migrations_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "db-service", "migrations")
)


@pytest.mark.asyncio
async def test_user_end_to_end():
    """
    End-to-end test for UserService that applies DB migrations, starts the
    gRPC server against a Postgres instance, exercises Register/Login/Get/Update/List
    and validates expected success and error cases.

    The test skips if the DB or migrations are not available. Set `DSN` env var
    to override the default (postgresql://postgres:postgres@db-service:5432/postgres).
    """

    dsn = os.getenv("DSN", "postgresql://postgres:postgres@db-service:5432/postgres")

    # Ensure migrations are present
    try:
        migrations = read_migrations(migrations_dir)
    except Exception as e:
        pytest.skip(f"Skipping e2e: failed to read migrations: {e}")

    # If migration-created helper table doesn't exist, apply migrations
    try:
        conn_check = psycopg2.connect(dsn)
        cur_check = conn_check.cursor()
        cur_check.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            ("platforms",),
        )
        platforms_exists = cur_check.fetchone()[0]
    except Exception:
        platforms_exists = False
    finally:
        try:
            cur_check.close()
        except Exception:
            pass
        try:
            conn_check.close()
        except Exception:
            pass

    if not platforms_exists:
        try:
            with get_backend(dsn) as backend:
                backend.apply_migrations(migrations)
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                pass
            else:
                pytest.skip(
                    f"Skipping e2e: cannot apply migrations or connect to DB: {e}"
                )

    # Verify migrations created the users table; if not, attempt to run migration apply_step
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            ("users",),
        )
        exists = cur.fetchone()[0]

        if not exists:
            files = sorted(glob.glob(os.path.join(migrations_dir, "*.py")))
            for f in files:
                try:
                    spec = importlib.util.spec_from_file_location(
                        "mig_" + os.path.basename(f), f
                    )
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "apply_step"):
                        mod.apply_step(conn)
                        conn.commit()
                except Exception as e:
                    print(f"Migration {f} apply failed: {e}")

            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
                ("users",),
            )
            exists = cur.fetchone()[0]

        if not exists:
            pytest.skip("Skipping e2e: migrations did not create users table")
    except Exception as e:
        pytest.skip(f"Skipping e2e: cannot run manual migrations: {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    logger = Logger("test")

    # Start async DB pool
    database = Database(logger=logger, dsn=dsn)
    try:
        await database.setup()
    except Exception as e:
        pytest.skip(f"Skipping e2e: cannot connect async DB pool: {e}")

    user_table = UserTable(logger=logger, database=database)

    service = UserService(
        logger=logger,
        user_table=user_table,
        jwt_secret="e2e-secret",
        jwt_expiration_hours=24,
    )

    # Start in-process gRPC server
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 200 * 1024 * 1024),
            ("grpc.max_send_message_length", 200 * 1024 * 1024),
        ]
    )
    user_pb2_grpc.add_UserServiceServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = user_pb2_grpc.UserServiceStub(channel)

    # Begin exercising endpoints and error cases
    email = f"e2e-user-{uuid.uuid4().hex}-{uuid.uuid4().hex}@example.com"
    password = "P@ssw0rd1"

    # 1) Register with invalid platform_id string -> INVALID_ARGUMENT
    bad_plat = user_pb2.RegisterRequest(
        email="badplat@example.com",
        password=password,
        password_confirm=password,
        first_name="Bad",
        last_name="Plat",
        platform_id="not-a-uuid",
    )
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Register(bad_plat)
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    # 2) Register without platform_id (required for non-superadmin) -> INVALID_ARGUMENT
    no_plat = user_pb2.RegisterRequest(
        email="no-platform@example.com",
        password=password,
        password_confirm=password,
        first_name="No",
        last_name="Platform",
    )
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Register(no_plat)
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    # 3) Successful Register
    platform_id = str(uuid.uuid4())
    req = user_pb2.RegisterRequest(
        email=email,
        password=password,
        password_confirm=password,
        first_name="E2E",
        last_name="User",
        platform_id=platform_id,
    )
    # Ensure no previous user with this email exists
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE lower(email) = lower($1)", email)
    # Ensure platform exists for FK constraint; if a platform for localhost exists, use its id
    async with database.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM platforms WHERE lower(domain_name) = lower($1)", "localhost"
        )
        if existing:
            platform_id = str(existing["id"])
            req.platform_id = platform_id
        else:
            await conn.execute(
                "INSERT INTO platforms (id, name, domain_name) VALUES ($1, $2, $3)",
                platform_id,
                "e2e-platform",
                "localhost",
            )

    resp = await stub.Register(req)
    assert resp.WhichOneof("response") == "success"
    assert resp.success.email == email
    user_id = resp.success.id

    # 4) Duplicate registration -> ALREADY_EXISTS
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Register(req)
    assert exc.value.code() == grpc.StatusCode.ALREADY_EXISTS

    # 5) Login missing credentials -> INVALID_ARGUMENT
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Login(user_pb2.LoginRequest(email="", password=""))
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    # 6) Login missing platform_id -> INVALID_ARGUMENT
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Login(user_pb2.LoginRequest(email=email, password=password))
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    # 7) Login wrong password -> UNAUTHENTICATED
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Login(
            user_pb2.LoginRequest(email=email, password="bad", platform_id=platform_id)
        )
    assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED

    # 8) Login success -> receive JWT
    login_resp = await stub.Login(
        user_pb2.LoginRequest(email=email, password=password, platform_id=platform_id)
    )
    assert login_resp.WhichOneof("response") == "success"
    token = login_resp.success.token
    assert token and isinstance(token, str)
    decoded = pyjwt.decode(token, "e2e-secret", algorithms=["HS256"])
    assert decoded.get("email", "").lower() == email.lower()
    owner_md = (("authorization", "Bearer " + token),)

    # 9) Get with owner token and no id -> returns owner
    get_resp = await stub.Get(user_pb2.GetRequest(), metadata=owner_md)
    assert get_resp.WhichOneof("response") == "success"
    assert get_resp.success.email.lower() == email.lower()

    # 10) Update as owner: change first_name -> success
    upd = user_pb2.UpdateRequest(id=user_id, first_name="NewName")
    upd_resp = await stub.Update(upd, metadata=owner_md)
    assert upd_resp.WhichOneof("response") == "success"
    assert upd_resp.success.first_name == "NewName"

    # 11) Owner cannot change is_active -> PERMISSION_DENIED
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Update(
            user_pb2.UpdateRequest(id=user_id, is_active=False), metadata=owner_md
        )
    assert exc.value.code() == grpc.StatusCode.PERMISSION_DENIED

    # 12) Owner update with password_confirm mismatch -> INVALID_ARGUMENT
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.Update(
            user_pb2.UpdateRequest(
                id=user_id, password="NewP@ss1", password_confirm="nope"
            ),
            metadata=owner_md,
        )
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    # 13) Create a superadmin token (no DB row required) to exercise admin-only paths
    payload_super = {
        "sub": str(uuid.uuid4()),
        "is_superadmin": True,
        "role": "superadmin",
    }
    token_super = pyjwt.encode(payload_super, "e2e-secret", algorithm="HS256")
    if isinstance(token_super, bytes):
        token_super = token_super.decode("utf-8")
    super_md = (("authorization", "Bearer " + token_super),)

    # 14) List as superadmin -> should include the created user
    list_req = user_pb2.ListRequest(limit=100, offset=0)
    got = []
    async for u in stub.List(list_req, metadata=super_md):
        got.append(u)
    assert any(g.email.lower() == email.lower() for g in got)

    # 15) List as regular user -> PERMISSION_DENIED
    with pytest.raises(grpc.aio.AioRpcError):
        async for _ in stub.List(list_req, metadata=owner_md):
            pass

    # Cleanup created records
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE lower(email) = lower($1)", email)

    await channel.close()
    await server.stop(0)
    await database.close()
