# Platform Microservice

This repository contains a collection of independent, production-oriented gRPC microservices that implement platform features such as admin, user, and invite management. The repo includes service source, container images, Postgres migrations, an example `admin-service` with a runnable end-to-end (`Register`) test, and an observability stack (LGTM) for logs, metrics, and traces. Follow the Quickstart below to apply migrations, run the admin E2E test, or bring up services via Docker Compose.

gRPC & Technology stack

This project is built as a set of gRPC microservices implemented in Python. Each service exposes gRPC endpoints (defined via Protobuf) and is usually routed through the `proxy-service` (Envoy). The `admin-service` `requirements.txt` (see `admin-service/requirements.txt`) shows the main libraries and stacks used:

- Core gRPC: `grpcio`, `grpcio-tools`, `googleapis-common-protos`, `grpcio-status`
- Auth & security: `bcrypt` (password hashing), `PyJWT` (JWT tokens)
- Database & migrations: `asyncpg` (async Postgres client), `psycopg2-binary` (dev), `yoyo-migrations`
- Validation & typing: `pydantic` (including `pydantic[email]`)
- Observability: `python-json-logger`, `prometheus_client`, OpenTelemetry (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-instrumentation-grpc`)
- Dev & testing: `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `isort`, and related tools

See `admin-service/requirements.txt` for the full dependency list and pinned versions.

## Microservices

This project is organized as a collection of independent microservices. Each service has its own source, dependencies, container image, and lifecycle so services can be developed, tested, and deployed independently.

Current and planned services (examples):
- `admin-service` — Admin user management and authentication. Current status: implemented through the `Register` flow and E2E test; additional admin endpoints still pending.
- `admin-invite-service` — Planned service to create, send, and validate admin invites.
- `user-service` — Planned service to manage regular user accounts and profiles.
- `platform-service` — Planned service for platform-level orchestration and shared APIs.
- `db-service` — Postgres instance and migrations used by services.
- `proxy-service` — Envoy-based proxy that routes gRPC requests to individual services.

Service independence
- Each service lives in its own directory with a `Dockerfile`, `requirements.txt`, an `app/` package (code and `proto/`), and service-scoped tests.
- Services communicate via gRPC and are usually exposed through the `proxy-service` (see `proxy-service/envoy.yaml`).
- Run, build, and test services independently using `docker-compose` with the single-service pattern: `docker-compose up -d <service-name>`.

Adding a new service (quick guide)
1. Create a new folder at the repo root, e.g. `my-service/`.
2. Add a `Dockerfile`, `requirements.txt`, and `app/` package with `server.py` and `proto/` definitions.
3. Add tests to `app/tests/`.
4. Add the service to `docker-compose.yml` and update `proxy-service/envoy.yaml` if it exposes gRPC over the proxy.
5. If the service needs DB migrations, add them to `db-service/migrations` or manage a separate migration plan.

Running & testing a single service
- Start the DB (and proxy if required): `docker-compose up -d db-service proxy-service`
- Start the service: `docker-compose up -d admin-service`
- Run tests inside the service container: `docker-compose run --rm admin-service pytest -q`

Notes & best practices
- Keep services focused and small; design clean, versioned gRPC APIs.
- Prefer API-driven interactions between services; avoid direct cross-service DB writes.
- Add metrics/logs/tracing for each service (observability is configured in this repo's `config/` folder).


Prerequisites
- Docker & Docker Compose installed and running

Quickstart (recommended — use Docker Compose)

1. Start the Postgres service

```bash
docker-compose up -d db-service
```

Wait until Postgres is ready. You can follow the logs:

```bash
docker-compose logs -f db-service
# look for: "database system is ready to accept connections"
```

2. Apply DB migrations

The repository includes `yoyo` migrations in `db-service/migrations` and a `yoyo.ini` config.

```bash
docker-compose run --rm migration-service yoyo apply
```

This runs the migration container (built from `db-service`) and applies migrations against the `db-service` Postgres instance.

3. Run the register end-to-end test

Run the test inside the `admin-service` container:

```bash
docker-compose run --rm admin-service pytest app/tests/test_register_e2e.py -q
```

This command runs the E2E test inside the same Docker network so the default DSN (`postgresql://postgres:postgres@db-service:5432/postgres`) works out-of-the-box.

Notes about the E2E test
- The test `app/tests/test_register_e2e.py` will attempt to apply migrations if they are missing, then start an in-process gRPC server and call the `Register` RPC using a `super_admin_email` bypass. The test also deletes the created admin record during cleanup.
Notes about the E2E test
- The test `app/tests/test_register_e2e.py` will attempt to apply migrations if they are missing, then start an in-process gRPC server and call the `Register` RPC using a `super_admin_email` bypass. The test also deletes the created admin record during cleanup.
 - The recommended execution method is inside the `admin-service` container (see Option A). Running tests directly on the host is not supported by this repository.

Troubleshooting
- If migrations fail with errors about existing objects, it usually means the tables already exist; inspect the DB and re-run if needed.
- If `docker-compose run --rm admin-service` cannot connect to `db-service`, make sure `db-service` is running (`docker-compose up -d db-service`) and check `docker-compose ps` and `docker-compose logs db-service`.
- To check Postgres readiness inside the container you can run:

```bash
docker-compose exec db-service pg_isready -U postgres
```

Observability (LGTM)

LGTM here is a short name used in this repo for the observability stack: Loki, Grafana, Tempo, and Mimir.

Endpoints (local):

- Grafana: http://localhost:3000 (admin / admin)
- Loki: http://localhost:3100
- Tempo: http://localhost:3200
- Mimir (Prometheus API): http://localhost:9090

Start only observability services:

```bash
docker-compose up -d grafana loki tempo mimir
```

Grafana is pre-provisioned with datasources for Loki, Tempo, and Mimir from `config/grafana/provisioning`.

Adjust configs under `config/` as needed for production.

Cleanup

```bash
docker-compose down
```

## Manual registration (grpcurl)

You can manually call the `Register` RPC using `grpcurl`. The admin service proto is available at [admin-service/app/proto/admin.proto](admin-service/app/proto/admin.proto).

Option A — run `grpcurl` directly in the running `admin-service` container (recommended)

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

Notes:
- `grpcurl` is installed in the `admin-service` image (see `admin-service/Dockerfile`).
- `proxy-service:8080` is proxy endpoint for all gRPC microservice (see `docker-compose.yml` and file `proxy-service/envoy.yaml`) 
- `admin@platfom-microservice.com` is SUPER_ADMIN_EMAIL (see `docker-compose.yml`)


Useful files
- [db-service/yoyo.ini](db-service/yoyo.ini)
- [db-service/migrations](db-service/migrations)
- [admin-service/app/tests/test_register_e2e.py](admin-service/app/tests/test_register_e2e.py)
- [config/grafana/provisioning](config/grafana/provisioning)

If you'd like, I can run the E2E test in the repo for you (I will need Docker available and permission to run containers). Would you like me to run it now?
