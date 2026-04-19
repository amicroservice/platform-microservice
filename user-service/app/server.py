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

import asyncio
import os

import grpc
from services.user import UserService
from utils.logger import Logger
from utils.observability import setup_observability

import proto.user_pb2_grpc as user_pb2_grpc
from db.pool import Database
from db.tables.user import UserTable


# Function to start and run the gRPC server
async def serve():
    # Get variables environments
    app_name = os.getenv("APP_NAME")
    port = os.getenv("GRPC_PORT")
    jwt_secret = os.getenv("JWT_SECRET")
    dsn = os.getenv("DSN")
    jwt_secret = os.getenv("JWT_SECRET")
    jwt_expiration_hours = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    # Setting logging
    logger = Logger(name=app_name)

    # Setup observability (Prometheus metrics, OpenTelemetry tracing, gRPC instrumentation)
    try:
        setup_observability(service_name=app_name, logger=logger)
    except Exception:
        logger.warning(f"{__name__}: Observability setup failed, continuing startup")

    # Create a database object
    database = Database(logger, dsn=dsn)

    # Connect to the database
    await database.setup()

    # Initial User Service
    user_table = UserTable(logger=logger, database=database)
    user_service = UserService(
        logger=logger,
        user_table=user_table,
        jwt_secret=jwt_secret,
        jwt_expiration_hours=jwt_expiration_hours,
    )

    # Start the async gRPC server
    max_message_size = 128 * 1024  # 128 KiB
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", max_message_size),
            ("grpc.max_send_message_length", max_message_size),
        ]
    )

    # Register the service implementation with the gRPC server
    user_pb2_grpc.add_UserServiceServicer_to_server(
        user_service,
        server,
    )

    # Bind the server to the specified port on all available network interfaces
    server.add_insecure_port("[::]:" + port)

    # Start the server in the background
    await server.start()

    # Log a startup message
    logger.info(f"{__name__}: Server started, listening on {port}")

    try:
        # Keep the server running until explicitly stopped
        await server.wait_for_termination()
    except asyncio.CancelledError:
        logger.info(f"{__name__}: Shutting down server...")

    # Shutdown gracefully
    await server.stop(grace=5)  # Graceful shutdown (in seconds)

    # Close the database connection
    await database.close()


# Entry point of the script
if __name__ == "__main__":
    asyncio.run(serve())  # Call the serve function to start the gRPC server
