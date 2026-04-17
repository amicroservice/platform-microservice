"""
Copyright 2024 Taufik Hidayat authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

gRPC server entrypoint for platform-service
"""

import asyncio
import os

import grpc
from services.platform import PlatformService
from utils.logger import Logger
from utils.observability import setup_observability

import proto.platform_pb2_grpc as platform_pb2_grpc
from db.pool import Database
from db.tables.platform import PlatformTable


async def serve():
    app_name = os.getenv("APP_NAME", "platform-service")
    port = os.getenv("GRPC_PORT", "50050")
    dsn = os.getenv("DSN")

    logger = Logger(name=app_name)

    try:
        setup_observability(service_name=app_name, logger=logger)
    except Exception:
        logger.warning(f"{__name__}: Observability setup failed, continuing startup")

    database = Database(logger, dsn=dsn)

    await database.setup()

    platform_table = PlatformTable(logger=logger, database=database)
    platform_service = PlatformService(logger=logger, platform_table=platform_table)
    jwt_secret = os.getenv("JWT_SECRET")
    platform_service.configure_jwt(jwt_secret)

    max_message_size = 128 * 1024
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", max_message_size),
            ("grpc.max_send_message_length", max_message_size),
        ]
    )

    platform_pb2_grpc.add_PlatformServiceServicer_to_server(platform_service, server)

    server.add_insecure_port("[::]:" + port)

    await server.start()

    logger.info(f"{__name__}: Server started, listening on {port}")

    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        logger.info(f"{__name__}: Shutting down server...")

    await server.stop(grace=5)

    await database.close()


if __name__ == "__main__":
    asyncio.run(serve())
