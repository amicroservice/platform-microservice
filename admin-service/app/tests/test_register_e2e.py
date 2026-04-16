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
import os
import pathlib
import sys

import pytest


def _find_repo_root(start_dir: str):
    cur = os.path.abspath(start_dir)
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, "db-service")):
            return cur
        parent = os.path.abspath(os.path.join(cur, ".."))
        if parent == cur:
            break
        cur = parent
    return None


# Make admin app importable from tests
repo_root = _find_repo_root(os.path.dirname(__file__)) or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
admin_app_dir = os.path.join(repo_root, "admin-service", "app")
sys.path.insert(0, os.path.abspath(admin_app_dir))

import glob
import importlib.util

import grpc
import psycopg2
from yoyo import get_backend, read_migrations

import proto.admin_pb2 as admin_pb2
import proto.admin_pb2_grpc as admin_pb2_grpc
from db.pool import Database
from db.tables.admin import AdminTable
from services.admin import AdminService
from utils.logger import Logger


@pytest.mark.asyncio
async def test_register_end_to_end():
    """
    End-to-end test that applies DB migrations, starts the AdminService gRPC
    server against a real Postgres instance, calls Register, and then
    deletes the created admin record.

    Requires a reachable Postgres instance. Set `DSN` env var to override
    the default (postgresql://postgres:postgres@127.0.0.1:5432/postgres).
    """

    dsn = os.getenv("DSN", "postgresql://postgres:postgres@db-service:5432/postgres")

    # Locate migrations directory relative to the repository root
    migrations_dir = os.path.abspath(
        os.path.join(repo_root, "db-service", "migrations")
    )

    # Apply migrations using yoyo. If migrations or DB are unavailable, skip test.
    try:
        migrations = read_migrations(migrations_dir)
    except Exception as e:
        pytest.skip(f"Skipping e2e: failed to read migrations: {e}")

        # Apply migrations using yoyo. If migrations or DB are unavailable, skip test.
        # If migration-created tables already exist, avoid re-applying migrations
        # (some environments may have DB objects created outside yoyo).
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
            migrations_dir2 = os.path.join(repo_root, "db-service", "migrations")
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

    # Create a channel and stub to call the Register endpoint
    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = admin_pb2_grpc.AdminServiceStub(channel)

    email = super_admin_email
    password = "P@ssw0rd1"

    request = admin_pb2.RegisterRequest(
        email=email,
        password=password,
        password_confirm=password,
        first_name="E2E",
        last_name="Tester",
    )

    try:
        resp = await stub.Register(request)
    except grpc.aio.AioRpcError as e:
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

    # Cleanup created admin record
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE lower(email) = lower($1)", email)

    await channel.close()
    await server.stop(0)
    await database.close()
