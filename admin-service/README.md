# Admin Service

This service implements admin user management and authentication for the Platform Microservice repository. It currently implements the `Register` and `Login` flows and includes runnable end-to-end tests.

gRPC & Technology stack

The admin service uses the same core stacks as the repo (see `admin-service/requirements.txt` for exact pins):

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Auth & security: `bcrypt` (password hashing), `PyJWT` (JWT tokens)
- Database & migrations: `asyncpg` (async Postgres client), `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic`
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry packages
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`

Microservice status

- `admin-service` — Admin user management and authentication. Current status: implemented through the `Register` flow and E2E test; additional admin endpoints still pending.

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
  -d '{"email":"admin@platfom-microservice.com","password":"s3c!reT1","password_confirm":"s3c!reT1","first_name":"Admin","last_name":"Platform"}' \
  proxy-service:8080 admin.AdminService/Register
```

3. Call the `Login` RPC (example):

```bash
docker-compose exec admin-service grpcurl -plaintext \
  -import-path /app/app/proto \
  -proto admin.proto \
  -d '{"email":"admin@platfom-microservice.com","password":"s3c!reT1"}' \
  proxy-service:8080 admin.AdminService/Login
```

Useful files

- `app/proto/admin.proto`
- `requirements.txt` (service dependencies)
- `tests/test_register_e2e.py`
- `tests/test_login_e2e.py`

Troubleshooting

- If migrations fail because objects already exist, inspect the DB state and re-run migrations as needed.
- If the admin container cannot connect to `db-service`, ensure `db-service` is running: `docker-compose up -d db-service` and check `docker-compose logs db-service` or `docker-compose ps`.

If you want, I can run the E2E test now inside the `admin-service` container. Want me to run it?