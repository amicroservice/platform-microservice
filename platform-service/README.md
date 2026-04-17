
# platform-service
Minimal, practical instructions for working with `platform-service`.

Overview

Platform microservice implementing platform-related gRPC APIs used by other services. The
service is implemented in `app/server.py` and the gRPC definitions live in
`app/proto/platform.proto`.

gRPC & Technology stack

The platform service uses the same core stacks as the repo (see `platform-service/requirements.txt` for exact pins):

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Database & migrations: `asyncpg` (async Postgres client), `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic`
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry packages
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`

Generate Python gRPC code

Option A — from the repository (local environment):

```bash
cd platform-service/app/proto
python -m grpc_tools.protoc -I . --python_out=. --pyi_out=. --grpc_python_out=. platform.proto
```

Option B — run inside the `platform-service` container (recommended when dependencies are installed in the container):

```bash
docker-compose exec platform-service sh -c "cd /app/app/proto && python -m grpc_tools.protoc -I . --python_out=. --pyi_out=. --grpc_python_out=. platform.proto"
```

Run (recommended — Docker Compose)

1. Start infrastructure (Postgres, etc.):

```bash
docker-compose up -d db-service
```

2. Apply DB migrations:

```bash
docker-compose run --rm migration-service yoyo apply
```

3. Build & start the platform service:

```bash
docker-compose up -d --build platform-service
```

Run tests

```bash
# Run tests inside the service container (recommended)
docker-compose run --rm platform-service pytest -q
```

Manual RPCs (grpcurl)


Authentication note: `Create` and `Update` require a superadmin JWT (token must include `is_superadmin: true`). `Get` and `List` do not require authentication.

1. Obtain a token (example)

Obtain a token from the `admin` service via `Login` and store it in `TOKEN`. Use the superadmin account (configured via `SUPER_ADMIN_EMAIL`) so the returned token includes `is_superadmin=true`. The example uses `jq` to extract the returned token (`Login` response contains `success.token`):

```bash
TOKEN=$(docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platform-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.AdminService/Login | jq -r '.success.token')
```

2. Create a platform (example)

The `Create` RPC accepts `name`, `domain_name`, and an optional `properties` object. This RPC requires a superadmin token — include the `authorization` metadata header:

```bash
docker-compose exec platform-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d '{"name":"Example Platform","domain_name":"example.com","properties":{"region":"us"}}' \
  proxy-service:8080 platform.PlatformService/Create
```

3. List platforms (get a `PLATFORM_ID`)

Use the `List` RPC to see available platforms and extract an ID for subsequent calls. The `List` RPC does not require authentication. The example below retrieves one platform and stores its `id` in `PLATFORM_ID`:

```bash
PLATFORM_ID=$(docker-compose exec platform-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d '{"limit":1,"offset":0,"order_by":"created_at"}' \
  proxy-service:8080 platform.PlatformService/List | jq -r '.id' | head -n1)

echo "PLATFORM_ID=$PLATFORM_ID"
```

4. Get a platform (example)

Use the `Get` RPC to fetch a platform by `id`. This RPC does not require authentication. Use the `PLATFORM_ID` obtained from the previous `List` call:

```bash
docker-compose exec platform-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d "{\"id\":\"$PLATFORM_ID\"}" \
  proxy-service:8080 platform.PlatformService/Get
```

4. Update a platform (example)

The `Update` RPC accepts partial fields; include `id` and any fields to change. This RPC requires a superadmin token — include the `authorization` metadata header:

```bash
docker-compose exec platform-service grpcurl -plaintext -H "authorization: Bearer $TOKEN" \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d "{\"id\":\"$PLATFORM_ID\",\"name\":\"New Name\",\"domain_name\":\"new.example.com\"}" \
  proxy-service:8080 platform.PlatformService/Update
```

5. List platforms (example)

The `List` RPC streams `Platform` messages; include `limit`/`offset` and filters as needed. This RPC does not require authentication:

```bash
docker-compose exec platform-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto platform.proto \
  -d '{"limit":50,"offset":0,"order_by":"created_at"}' \
  proxy-service:8080 platform.PlatformService/List
```

The proto is available at `app/proto/platform.proto`.

Useful files

- `app/proto/platform.proto`
- `app/server.py`
- `requirements.txt`
- `tests/test_platform_e2e.py`
- `tests/test_platform_service_unit.py`

Troubleshooting

- If the service cannot connect to Postgres, ensure `db-service` is running and reachable.
- If migrations fail, inspect the database state and re-run migrations.
- If gRPC stubs are missing, re-run the `protoc` command above.

Development notes

- Use a virtualenv and install dependencies: `pip install -r platform-service/requirements.txt`
- Regenerate protos after editing `platform.proto`.
- Run unit and E2E tests with `pytest`.

Service defaults
- gRPC port: `50050` (container)
- Metrics port: `8000` (container; mapped to host `8000`)
