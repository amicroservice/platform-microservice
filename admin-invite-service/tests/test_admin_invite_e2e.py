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

import app.proto.admin_invite_pb2 as invite_pb2
import app.proto.admin_invite_pb2_grpc as invite_pb2_grpc
from app.db.pool import Database
from app.db.tables.admin_invites import AdminInviteTable
from app.services.admin_invite import AdminInviteService
from app.utils.logger import Logger

# Locate migrations directory relative to this test file
migrations_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "db-service", "migrations")
)


@pytest.mark.asyncio
async def test_admin_invite_end_to_end():
    dsn = os.getenv("DSN", "postgresql://postgres:postgres@db-service:5432/postgres")

    # Apply migrations using yoyo. If migrations or DB are unavailable, skip test.
    try:
        migrations = read_migrations(migrations_dir)
    except Exception as e:
        pytest.skip(f"Skipping e2e: failed to read migrations: {e}")

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

    # Verify platforms table exists
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            ("platforms",),
        )
        exists = cur.fetchone()[0]

        if not exists:
            # Attempt to apply migrations by importing each migration module and
            # running its `apply_step(conn)` function (same fallback used in
            # admin-service e2e tests).
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

    database = Database(logger=logger, dsn=dsn)
    try:
        await database.setup()
    except Exception as e:
        pytest.skip(f"Skipping e2e: cannot connect async DB pool: {e}")

    invite_table = AdminInviteTable(logger=logger, database=database)
    jwt_secret = "e2e-secret"
    service = AdminInviteService(
        logger=logger, invite_table=invite_table, jwt_secret=jwt_secret
    )

    server = grpc.aio.server()
    invite_pb2_grpc.add_AdminInviteServiceServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = invite_pb2_grpc.AdminInviteServiceStub(channel)

    try:
        # ensure a platform exists
        platform_id = None
        try:
            async with database.pool.acquire() as conn:
                # Remove any existing platform with the same domain to avoid unique
                # constraint violations when running repeated e2e tests in the
                # shared database used by CI/dev environments.
                try:
                    await conn.execute(
                        "DELETE FROM platforms WHERE lower(domain_name) = lower($1)",
                        "e2e.example.com",
                    )
                except Exception:
                    # Ignore delete errors; we'll attempt to insert and skip if it fails
                    pass

                record = await conn.fetchrow(
                    "INSERT INTO platforms (name, domain_name) VALUES ($1, $2) RETURNING id",
                    "e2e-platform",
                    "e2e.example.com",
                )
                platform_id = record["id"]
        except Exception:
            pytest.skip("Skipping e2e: cannot create platform record")

        # create superadmin token and ensure the inviter admin exists (fk)
        inviter_id = str(uuid.uuid4())
        payload = {"is_superadmin": True, "role": "superadmin", "sub": inviter_id}
        token = pyjwt.encode(payload, jwt_secret, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")

        # Insert a matching admin record so inviter_id FK constraint is satisfied
        try:
            async with database.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO admins (id, email, password_hash, first_name, last_name, is_superadmin) VALUES ($1, $2, $3, $4, $5, $6)",
                    inviter_id,
                    f"inviter-{inviter_id[:8]}@example.com",
                    b"",
                    "Inviter",
                    "E2E",
                    True,
                )
        except Exception:
            pytest.skip("Skipping e2e: cannot create inviter admin record")

        # Create invite
        req = invite_pb2.CreateRequest(
            email="invite-e2e@example.com", platform_id=str(platform_id)
        )
        resp = await stub.Create(req, metadata=(("authorization", "Bearer " + token),))
        assert resp.WhichOneof("response") == "success"

        invite_id = resp.success.id

        # List invites
        list_req = invite_pb2.ListRequest(limit=10, offset=0)
        got = []
        async for inv in stub.List(
            list_req, metadata=(("authorization", "Bearer " + token),)
        ):
            got.append(inv)

        assert any(i.email == "invite-e2e@example.com" for i in got)

        # Get invite
        get_resp = await stub.Get(
            invite_pb2.GetRequest(id=invite_id),
            metadata=(("authorization", "Bearer " + token),),
        )
        assert get_resp.WhichOneof("response") == "success"

        # Delete invite
        del_resp = await stub.Delete(
            invite_pb2.DeleteRequest(id=invite_id, platform_id=str(platform_id)),
            metadata=(("authorization", "Bearer " + token),),
        )
        assert del_resp.WhichOneof("response") == "success"
    finally:
        # Ensure we always close channel and stop the server to avoid destructor
        # scheduling shutdown after the event loop is closed.
        try:
            await channel.close()
        except Exception:
            pass
        try:
            await server.stop(0)
        except Exception:
            pass
        # Wait for termination if available
        try:
            if hasattr(server, "wait_for_termination"):
                await server.wait_for_termination()
        except Exception:
            pass
        try:
            await database.close()
        except Exception:
            pass
