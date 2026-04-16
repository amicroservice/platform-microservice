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
import proto.admin_pb2_grpc as admin_pb2_grpc
from db.pool import Database
from db.tables.admin import AdminTable
from services.admin import AdminService
from utils.logger import Logger
from utils.observability import setup_observability


# Function to start and run the gRPC server
async def serve():
    # Get variables environments
    app_name = os.getenv("APP_NAME")
    port = os.getenv("GRPC_PORT")
    jwt_secret = os.getenv("JWT_SECRET")
    dsn = os.getenv("DSN")
    super_admin_email = os.getenv("SUPER_ADMIN_EMAIL")

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

    # Initial Admin Service
    admin_table = AdminTable(logger=logger, database=database)
    admin_service = AdminService(
        logger=logger,
        admin_table=admin_table,
        jwt_secret=jwt_secret,
        super_admin_email=super_admin_email,
    )

    # Initial Admin Table
    admin_table = AdminTable(logger=logger, database=database)

    # Start the async gRPC server
    max_message_size = 200 * 1024 * 1024  # 200 MiB
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", max_message_size),
            ("grpc.max_send_message_length", max_message_size),
        ]
    )

    # Register the service implementation with the gRPC server
    admin_pb2_grpc.add_AdminServiceServicer_to_server(
        admin_service,
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
