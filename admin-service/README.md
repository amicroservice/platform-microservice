# Admin Service

This service implements admin user management and authentication for the Platform Microservice repository. It implements the `Register` and `Login` flows and other admin APIs; all endpoints are implemented and covered by unit and end-to-end tests.

gRPC & Technology stack

The admin service uses the same core stacks as the repo (see `admin-service/requirements.txt` for exact pins):

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Auth & security: `bcrypt` (password hashing), `PyJWT` (JWT tokens)
- Database & migrations: `asyncpg` (async Postgres client), `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic`
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry packages
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`

Microservice status

- `admin-service` — Admin user management and authentication. Current status: implemented; all endpoints completed and covered by unit and end-to-end tests.

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

3. Start the admin service:

```bash
docker-compose up -d admin-service
```

4. Run tests inside the admin-service container (recommended so the default DSN and network are available):

```bash
docker-compose run --rm admin-service pytest -q
```

Run specific end-to-end tests:

```bash
docker-compose run --rm admin-service pytest tests/test_register_e2e.py -q

docker-compose run --rm admin-service pytest tests/test_login_e2e.py -q
```

Notes about the E2E tests

- The E2E tests will attempt to apply migrations if they are missing, start an in-process gRPC server, call the RPCs (`Register` and `Login`), and delete created records during cleanup.
- The recommended execution method is inside the `admin-service` container (so the default DSN `postgresql://postgres:postgres@db-service:5432/postgres` works).

Manual RPCs (grpcurl)

You can call the service RPCs using `grpcurl`. The admin proto is available at `app/proto/admin.proto`.

Option A — run `grpcurl` in the running `admin-service` container (recommended):

1. Start the admin service:

```bash
docker-compose up -d admin-service
```

2. Call the `Register` RPC (example):

```bash
docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platform-microservice.com","password":"s3c!reT1","password_confirm":"s3c!reT1","first_name":"Admin","last_name":"Platform"}' \
  proxy-service:8080 admin.AdminService/Register
```

3. Call the `Login` RPC (example):

```bash
docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.AdminService/Login
```
Authentication note: `Get`, `Update`, and `List` require authentication — pass a valid JWT as the `authorization` metadata header (`Bearer <token>`).

Obtain a token via `Login` and store it in `TOKEN` (example uses `jq` to extract the JSON token; adjust the `jq` path if your grpcurl output differs):

```bash
TOKEN=$(docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.AdminService/Login | jq -r '.success.token')
```

4. Call the `Get` RPC (example) with `authorization` header; omit `id` to retrieve the current authenticated admin and extract `ADMIN_ID` from the response:

```bash
ADMIN_ID=$(docker-compose exec admin-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{}' \
  proxy-service:8080 admin.AdminService/Get | jq -r '.success.id')
```

5. Call the `Update` RPC (example) with `authorization` header (use the `ADMIN_ID` extracted above):

```bash
docker-compose exec admin-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d "{\"id\":\"$ADMIN_ID\",\"email\":\"new@example.com\",\"first_name\":\"New\",\"last_name\":\"Name\"}" \
  proxy-service:8080 admin.AdminService/Update
```

6. Call the `List` RPC (example) — uses `limit`/`offset` and filters per `ListRequest` — include `authorization` header:

```bash
docker-compose exec admin-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"limit":50,"offset":0,"order_by":"created_at"}' \
  proxy-service:8080 admin.AdminService/List
```

Filter example (by top-level column):

```bash
docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"filters":{"email":"admin@platform-microservice.com"}}' \
  proxy-service:8080 admin.AdminService/List
```

If you want all admins with no filters, use `-d '{}'`.

Useful files

- `app/proto/admin.proto`
- `requirements.txt` (service dependencies)
- `tests/test_register_e2e.py`
- `tests/test_login_e2e.py`

Troubleshooting

- If migrations fail because objects already exist, inspect the DB state and re-run migrations as needed.
- If the admin container cannot connect to `db-service`, ensure `db-service` is running: `docker-compose up -d db-service` and check `docker-compose logs db-service` or `docker-compose ps`.
