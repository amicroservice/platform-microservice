# Admin Invite Service

Minimal, practical instructions for working with the admin-invite microservice.

## Overview

The Admin Invite Service implements gRPC endpoints to create, list, retrieve,
and delete admin invitation records used to invite administrators to a
platform. The service implementation lives in `app/server.py` and the gRPC
definitions are in `app/proto/admin_invite.proto`.

## gRPC & Technology stack

The service uses the common stacks used across this repository (see
`admin-invite-service/requirements.txt` for exact pins):

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Database & migrations: `asyncpg`, `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic`
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry packages
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`

## Generate Python gRPC code

Option A — from the repository (local environment):

```bash
cd admin-invite-service/app/proto
python -m grpc_tools.protoc -I . --python_out=. --pyi_out=. --grpc_python_out=. admin_invite.proto
```

Option B — run inside the `admin-invite-service` container (recommended when dependencies are installed there):

```bash
docker compose exec admin-invite-service sh -c "cd /app/app/proto && python -m grpc_tools.protoc -I . --python_out=. --pyi_out=. --grpc_python_out=. admin_invite.proto"
```

## Run (recommended — Docker Compose)

1. Start infra (Postgres):

```bash
docker compose up -d db-service
```

2. Apply DB migrations:

```bash
docker compose run --rm migration-service yoyo apply
```

3. Start the admin-invite service:

```bash
docker compose up -d admin-invite-service
```

## Run tests

Run tests inside the service container (recommended so the default DSN and network are available):

```bash
docker compose run --rm admin-invite-service pytest -q
```

Run the end-to-end tests:

```bash
docker compose run --rm admin-invite-service pytest tests/test_admin_invite_e2e.py -q
```

## Manual RPCs (grpcurl)

All RPCs in this service require a superadmin JWT (token must include `is_superadmin: true`).

1. Obtain a token from the `admin` service via `Login` and store it in `TOKEN` (example):

```bash
TOKEN=$(docker compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.AdminService/Login | jq -r '.success.token')
```

2. Create a platform (example) and extract `PLATFORM_ID` (create this BEFORE creating invites):

```bash
# Create a platform and capture its id
PLATFORM_ID=$(docker compose exec platform-service grpcurl -plaintext \
	-import-path /app/app/proto \
	-proto platform.proto \
	-d '{"name":"Example Platform","domain_name":"example.com","properties":{"region":"us"}}' \
	proxy-service:8080 platform.PlatformService/Create | jq -r '.success.id')
echo "PLATFORM_ID=$PLATFORM_ID"
```

3. Create an invite (example) using the `PLATFORM_ID` created above — this example also captures `INVITE_ID` automatically:

```bash
# Build the invite payload safely with jq to avoid complex escaping
INVITE_PAYLOAD=$(jq -n --arg email "invitee@example.com" --arg platform_id "$PLATFORM_ID" '{email:$email, platform_id:$platform_id}')

INVITE_ID=$(docker compose exec admin-invite-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
	-import-path /app/app/proto \
	-proto admin_invite.proto \
	-d "$INVITE_PAYLOAD" \
	proxy-service:8080 admin_invite.AdminInviteService/Create | jq -r '.success.id')

echo "INVITE_ID=$INVITE_ID"
```

3. List invites (streaming RPC) — include the authorization header:

```bash
docker compose exec admin-invite-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin_invite.proto \
  -d '{"limit":50,"offset":0,"order_by":"created_at"}' \
  proxy-service:8080 admin_invite.AdminInviteService/List
```

4. Get an invite (example):

```bash
# Build the get payload using the previously-captured $INVITE_ID
GET_PAYLOAD=$(jq -n --arg id "$INVITE_ID" '{id:$id}')

docker compose exec admin-invite-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin_invite.proto \
  -d "$GET_PAYLOAD" \
  proxy-service:8080 admin_invite.AdminInviteService/Get
```

5. Delete an invite (example):

```bash
# Build the delete payload using previously-captured $INVITE_ID and $PLATFORM_ID
DELETE_PAYLOAD=$(jq -n --arg id "$INVITE_ID" --arg platform_id "$PLATFORM_ID" '{id:$id, platform_id:$platform_id}')

docker compose exec admin-invite-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin_invite.proto \
  -d "$DELETE_PAYLOAD" \
  proxy-service:8080 admin_invite.AdminInviteService/Delete
```

## Useful files

- `app/proto/admin_invite.proto`
- `app/server.py`
- `requirements.txt`
- `tests/test_admin_invite_e2e.py`
- `tests/test_admin_invite_service_unit.py`

## Troubleshooting

- If the service cannot connect to Postgres, ensure `db-service` is running: `docker compose up -d db-service` and check `docker compose logs db-service`.
- If migrations fail, inspect the DB state and re-run migrations.
- If gRPC stubs are missing, regenerate them with the `protoc` command above.

## Service defaults

- gRPC port: `50051` (container)
- Metrics port: `8000` (container; Prometheus endpoint)

