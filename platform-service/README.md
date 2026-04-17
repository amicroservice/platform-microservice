
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

You can call the service RPCs using `grpcurl`. The proto is available at
`app/proto/platform.proto`.

```bash
docker-compose exec platform-service grpcurl -plaintext \
     -import-path /app/app/proto \
     -proto platform.proto \
     proxy-service:8080 platform.PlatformService/YourMethod
```

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
