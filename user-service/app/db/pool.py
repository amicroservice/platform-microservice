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

import asyncpg
from utils.logger import Logger


class Database:
    """
    Implement Pool database
    """

    def __init__(self, logger: Logger, dsn: str):
        # Initialize
        self.logger = logger
        self.dsn = dsn
        self.pool: asyncpg.pool.Pool = None

    async def setup(self):
        try:
            self.pool = await asyncpg.create_pool(dsn=self.dsn)
            self.logger.info(
                f"{__name__}: Connection to PostgreSQL database is established successfully!"
            )
        except Exception as e:
            self.logger.critical(f"{__name__}: Error connecting to database: {e}")
            raise e

    async def close(self):
        if self.pool:
            await self.pool.close()

            self.pool = None
            self.logger.info(f"{__name__}: Connection closed.")
