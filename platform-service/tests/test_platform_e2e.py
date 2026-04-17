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

import grpc
import jwt as pyjwt
import psycopg2
import pytest
from yoyo import get_backend, read_migrations

import app.proto.platform_pb2 as platform_pb2
import app.proto.platform_pb2_grpc as platform_pb2_grpc
from app.db.pool import Database
from app.db.tables.platform import PlatformTable
from app.services.platform import PlatformService
from app.utils.logger import Logger


@pytest.mark.asyncio
async def test_platform_end_to_end():
    """
    End-to-end test that applies DB migrations, starts the PlatformService gRPC
    server against a real Postgres instance, calls Create, exercises Get,
    Update and List, and then deletes the created platform record.

    Requires a reachable Postgres instance. Set `DSN` env var to override
    the default (postgresql://postgres:postgres@db-service:5432/postgres).
    """

    dsn = os.getenv("DSN", "postgresql://postgres:postgres@db-service:5432/postgres")

    # Locate migrations directory relative to this test file
    migrations_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "db-service", "migrations")
    )

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
            ("platforms",),
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
                ("platforms",),
            )
            exists = cur.fetchone()[0]

        if not exists:
            pytest.skip("Skipping e2e: migrations did not create platforms table")
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

    # Start database connection (asyncpg) used by PlatformTable
    database = Database(logger=logger, dsn=dsn)
    try:
        await database.setup()
    except Exception as e:
        pytest.skip(f"Skipping e2e: cannot connect async DB pool: {e}")

    platform_table = PlatformTable(logger=logger, database=database)

    # Create service
    service = PlatformService(logger=logger, platform_table=platform_table)
    # Provide JWT secret used by the test to authenticate Create calls
    service.configure_jwt("e2e-secret")

    # Start an in-process gRPC server on an ephemeral port
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 200 * 1024 * 1024),
            ("grpc.max_send_message_length", 200 * 1024 * 1024),
        ]
    )
    platform_pb2_grpc.add_PlatformServiceServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    # Create a channel and stub to call the Create endpoint
    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = platform_pb2_grpc.PlatformServiceStub(channel)

    # Generate a superadmin JWT
    payload = {"is_superadmin": True}
    token = pyjwt.encode(payload, "e2e-secret", algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    request = platform_pb2.CreateRequest(
        name="E2E Platform",
        domain_name="e2e.example.com",
    )

    try:
        resp = await stub.Create(
            request, metadata=(("authorization", "Bearer " + token),)
        )
    except grpc.aio.AioRpcError:
        # If RPC failed, attempt cleanup and re-raise for test failure
        async with database.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM platforms WHERE lower(domain_name) = lower($1)",
                "e2e.example.com",
            )
        await channel.close()
        await server.stop(0)
        await database.close()
        raise

    assert resp.WhichOneof("response") == "success"
    assert resp.success.domain_name == "e2e.example.com"

    created_id = resp.success.id

    # Verify Get
    get_resp = await stub.Get(platform_pb2.GetRequest(id=created_id))
    assert get_resp.WhichOneof("response") == "success"
    assert get_resp.success.id == created_id
    assert get_resp.success.name == "E2E Platform"

    # Verify Update (only change name so cleanup by domain still works)
    update_req = platform_pb2.UpdateRequest(id=created_id, name="E2E Platform Updated")
    update_resp = await stub.Update(
        update_req, metadata=(("authorization", "Bearer " + token),)
    )
    assert update_resp.WhichOneof("response") == "success"
    assert update_resp.success.name == "E2E Platform Updated"

    # Confirm update via Get
    get_resp2 = await stub.Get(platform_pb2.GetRequest(id=created_id))
    assert get_resp2.WhichOneof("response") == "success"
    assert get_resp2.success.name == "E2E Platform Updated"

    # Verify List returns the created platform
    list_req = platform_pb2.ListRequest(
        limit=10, offset=0, filters={"domain_name": "e2e.example.com"}
    )
    listed = []
    async for p in stub.List(list_req):
        listed.append(p)
    assert any(p.id == created_id for p in listed)

    # Cleanup created platform record
    async with database.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM platforms WHERE lower(domain_name) = lower($1)",
            "e2e.example.com",
        )

    await channel.close()
    await server.stop(0)
    await database.close()
