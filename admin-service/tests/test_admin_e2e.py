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

import app.proto.admin_pb2 as admin_pb2
import app.proto.admin_pb2_grpc as admin_pb2_grpc
import grpc
import jwt as pyjwt
import psycopg2
import pytest
from app.db.pool import Database
from app.db.tables.admin import AdminTable
from app.services.admin import AdminService
from app.utils.logger import Logger
from yoyo import get_backend, read_migrations

# Locate migrations directory relative to this test file
migrations_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "db-service", "migrations")
)


@pytest.mark.asyncio
async def test_admin_end_to_end():
    """
    End-to-end test that applies DB migrations, starts the AdminService gRPC
    server against a real Postgres instance, calls Register and Login,
    validates the returned JWT, and then deletes the created admin record.

    Requires a reachable Postgres instance. Set `DSN` env var to override
    the default (postgresql://postgres:postgres@db-service:5432/postgres).
    """

    dsn = os.getenv("DSN", "postgresql://postgres:postgres@db-service:5432/postgres")

    # Apply migrations using yoyo. If migrations or DB are unavailable, skip test.
    try:
        migrations = read_migrations(migrations_dir)
    except Exception as e:
        pytest.skip(f"Skipping e2e: failed to read migrations: {e}")

    # If migration-created tables already exist, avoid re-applying migrations
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
            # If migrations fail because DB objects already exist, continue; otherwise skip.
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                pass
            else:
                pytest.skip(
                    f"Skipping e2e: cannot apply migrations or connect to DB: {e}"
                )

    # Verify migrations created the required tables; if not, attempt a manual apply
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            ("admins",),
        )
        exists = cur.fetchone()[0]

        if not exists:
            # Apply each migration module's apply_step(conn)
            migrations_dir2 = migrations_dir
            files = sorted(glob.glob(os.path.join(migrations_dir2, "*.py")))
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
                    # continue if migration fails (may already be applied)
                    print(f"Migration {f} apply failed: {e}")

            # re-check
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
                ("admins",),
            )
            exists = cur.fetchone()[0]

        if not exists:
            pytest.skip("Skipping e2e: migrations did not create admins table")
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

    # Start database connection (asyncpg) used by AdminTable
    database = Database(logger=logger, dsn=dsn)
    try:
        await database.setup()
    except Exception as e:
        pytest.skip(f"Skipping e2e: cannot connect async DB pool: {e}")

    admin_table = AdminTable(logger=logger, database=database)

    # Create service (use a super-admin email so invite check is bypassed)
    super_admin_email = "e2e-super@example.com"
    service = AdminService(
        logger=logger,
        admin_table=admin_table,
        jwt_secret="e2e-secret",
        jwt_expiration_hours=24,
        super_admin_email=super_admin_email,
    )

    # Start an in-process gRPC server on an ephemeral port
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 200 * 1024 * 1024),
            ("grpc.max_send_message_length", 200 * 1024 * 1024),
        ]
    )
    admin_pb2_grpc.add_AdminServiceServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    # Create a channel and stub to call the Register and Login endpoints
    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = admin_pb2_grpc.AdminServiceStub(channel)

    email = super_admin_email
    password = "P@ssw0rd1"

    # Register the admin
    request = admin_pb2.RegisterRequest(
        email=email,
        password=password,
        password_confirm=password,
        first_name="E2E",
        last_name="Tester",
    )

    try:
        resp = await stub.Register(request)
    except grpc.aio.AioRpcError:
        # If RPC failed, attempt cleanup and re-raise for test failure
        async with database.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM admins WHERE lower(email) = lower($1)", email
            )
        await channel.close()
        await server.stop(0)
        await database.close()
        raise

    assert resp.WhichOneof("response") == "success"
    assert resp.success.email == email

    # Now attempt login
    login_req = admin_pb2.LoginRequest(email=email, password=password)
    login_resp = await stub.Login(login_req)
    assert login_resp.WhichOneof("response") == "success"
    token = login_resp.success.token
    assert token and isinstance(token, str)

    # Validate JWT payload
    decoded = pyjwt.decode(token, "e2e-secret", algorithms=["HS256"])
    assert decoded.get("email", "").lower() == email.lower()

    # Verify Get with superadmin token returns the created admin
    get_req = admin_pb2.GetRequest(id=resp.success.id)
    get_resp = await stub.Get(get_req, metadata=(("authorization", "Bearer " + token),))
    assert get_resp.WhichOneof("response") == "success"
    assert get_resp.success.email.lower() == email.lower()

    # Cleanup created admin record
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE lower(email) = lower($1)", email)

    await channel.close()
    await server.stop(0)
    await database.close()
