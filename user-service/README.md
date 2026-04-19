# User Service

This service implements user account management and authentication for the Platform Microservice repository. It implements the `Register` and `Login` flows and other user APIs; all endpoints are implemented and covered by unit and end-to-end tests.

gRPC & Technology stack

The user service uses the same core stacks as the repo (see `user-service/requirements.txt` for exact pins):

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Auth & security: `bcrypt` (password hashing), `PyJWT` (JWT tokens)
- Database & migrations: `asyncpg` (async Postgres client), `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic`
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry packages
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`

Microservice status

- `user-service` — User account management and authentication. Current status: implemented; all endpoints completed and covered by unit and end-to-end tests.

Running & testing this service (recommended — use Docker Compose)

1. Start Postgres (and proxy if required):

```bash
docker-compose up -d db-service
# or if proxy needed:
# docker-compose up -d db-service proxy-service
```

2. Apply DB migrations (runs the migration container and applies migrations against `db-service`):

```bash
docker-compose run --rm migration-service yoyo apply
```

3. Start the user service:

```bash
docker-compose up -d user-service
```

4. Run tests inside the user-service container (recommended so the default DSN and network are available):

```bash
docker-compose run --rm user-service pytest -q
```

Run specific end-to-end tests:

```bash
docker-compose run --rm user-service pytest tests/test_user_e2e.py -q

docker-compose run --rm user-service pytest tests/test_user_service_unit.py -q
```

Notes about the E2E tests

- The E2E tests will attempt to apply migrations if they are missing, start an in-process gRPC server, call the RPCs (`Register` and `Login`), and delete created records during cleanup.
- The recommended execution method is inside the `user-service` container (so the default DSN `postgresql://postgres:postgres@db-service:5432/postgres` works).

Manual RPCs (grpcurl)

You can call the service RPCs using `grpcurl`. The user proto is available at `app/proto/user.proto`.

Option A — run `grpcurl` in the running `user-service` container (recommended):

1. Start the user service:

```bash
docker-compose up -d user-service
```

2. Call the `Register` RPC (example):

```bash
docker-compose exec user-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{"email":"user@platform-microservice.com","password":"s3c!reT1","password_confirm":"s3c!reT1","first_name":"User","last_name":"Platform"}' \
  proxy-service:8080 admin.UserService/Register
```

3. Call the `Login` RPC (example):

```bash
docker-compose exec user-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{"email":"user@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.UserService/Login
```
Authentication note: `Get`, `Update`, and `List` require authentication — pass a valid JWT as the `authorization` metadata header (`Bearer <token>`). Note that `List` additionally requires elevated privileges (see below).

Obtain a token via `Login` and store it in `TOKEN` (example uses `jq` to extract the JSON token; adjust the `jq` path if your grpcurl output differs):

```bash
TOKEN=$(docker-compose exec user-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{"email":"user@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.UserService/Login | jq -r '.success.token')
```

4. Call the `Get` RPC (example) with `authorization` header; omit `id` to retrieve the current authenticated user and extract `USER_ID` from the response:

```bash
USER_ID=$(docker-compose exec user-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{}' \
  proxy-service:8080 admin.UserService/Get | jq -r '.success.id')
```

5. Call the `Update` RPC (example) with `authorization` header (use the `USER_ID` extracted above):

```bash
docker-compose exec user-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto user.proto \
  -d "{\"id\":\"$USER_ID\",\"email\":\"new@example.com\",\"first_name\":\"New\",\"last_name\":\"Name\"}" \
  proxy-service:8080 admin.UserService/Update
```

Cross-service example — create platform, register, and login (jq + grpcurl)

The following shows a full flow using `grpcurl` and `jq` to:

- create a new platform
- register a user scoped to that platform
- login the registered user and capture a JWT

Run these commands from the repo root. Ensure `db-service`, the proxy, and the services are running (`docker-compose up -d db-service proxy-service platform-service user-service`).

1) Obtain a superadmin token (adjust email/password to match your configured superadmin):

```bash
SUPER_PAYLOAD=$(jq -n --arg email "admin@platform-microservice.com" --arg password "s3c!reT1" '{email:$email, password:$password}')
TOKEN=$(docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d "$SUPER_PAYLOAD" \
  proxy-service:8080 admin.AdminService/Login | jq -r '.success.token')
echo "SUPERADMIN_TOKEN=$TOKEN"
```

2) Create a platform and capture `PLATFORM_ID` (requires the superadmin token):

```bash
PLATFORM_PAYLOAD=$(jq -n --arg name "Example Platform" --arg domain "example.com" --arg region "us" '{name:$name, domain_name:$domain, properties:{region:$region}}')
PLATFORM_ID=$(docker-compose exec platform-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d "$PLATFORM_PAYLOAD" \
  proxy-service:8080 platform.PlatformService/Create | jq -r '.success.id')
echo "PLATFORM_ID=$PLATFORM_ID"
```

3) Register a user against the new platform:

```bash
REGISTER_PAYLOAD=$(jq -n --arg email "user@example.com" --arg password "P@ssw0rd1" --arg first "User" --arg last "Example" --arg platform_id "$PLATFORM_ID" '{email:$email, password:$password, password_confirm:$password, first_name:$first, last_name:$last, platform_id:$platform_id}')
USER_ID=$(docker-compose exec user-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto user.proto \
  -d "$REGISTER_PAYLOAD" \
  proxy-service:8080 admin.UserService/Register | jq -r '.success.id')
echo "USER_ID=$USER_ID"
```

4) Login the newly-registered user scoped to the platform (capture a JWT):

```bash
LOGIN_PAYLOAD=$(jq -n --arg email "user@example.com" --arg password "P@ssw0rd1" --arg platform_id "$PLATFORM_ID" '{email:$email, password:$password, platform_id:$platform_id}')
USER_TOKEN=$(docker-compose exec user-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto user.proto \
  -d "$LOGIN_PAYLOAD" \
  proxy-service:8080 admin.UserService/Login | jq -r '.success.token')
echo "USER_TOKEN=$USER_TOKEN"
```

5) Call the `List` RPC (example) — uses `limit`/`offset` and filters per `ListRequest` — include `authorization` header.

Authorization/Permissions: The `List` RPC is restricted to administrative roles. Only a superadmin or an admin token scoped to the same `platform_id` can successfully call `List`. Calls with regular user tokens will return `permission_denied`. When listing users for a platform, include an appropriate `platform_id` filter and a token with admin privileges for that platform.

```bash
docker-compose exec user-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{"limit":50,"offset":0,"order_by":"created_at"}' \
  proxy-service:8080 admin.UserService/List
```

Filter example (by top-level column):

```bash
docker-compose exec user-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto user.proto \
  -d '{"filters":{"email":"user@platform-microservice.com"}}' \
  proxy-service:8080 admin.UserService/List
```

If you want all users with no filters, use `-d '{}'`.


Notes

- Replace example emails, passwords, and platform properties as needed.
- Use `jq` to safely build JSON payloads and to extract IDs/tokens from `grpcurl` output.

Useful files

- `app/proto/user.proto`
- `requirements.txt` (service dependencies)
- `tests/test_user_e2e.py`
- `tests/test_user_service_unit.py`

Troubleshooting

- If migrations fail because objects already exist, inspect the DB state and re-run migrations as needed.
- If the user container cannot connect to `db-service`, ensure `db-service` is running: `docker-compose up -d db-service` and check `docker-compose logs db-service` or `docker-compose ps`.
