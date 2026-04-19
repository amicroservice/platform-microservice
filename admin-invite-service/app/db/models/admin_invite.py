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

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from pydantic import BaseModel, EmailStr, model_validator


class AdminInviteBase(BaseModel):
    email: EmailStr
    inviter_id: Optional[uuid.UUID] = None
    is_used: bool = False
    platform_id: uuid.UUID

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def ensure_platform(self):
        if self.platform_id is None:
            raise ValueError("platform_id must be provided")
        return self


class AdminInviteCreate(BaseModel):
    email: EmailStr
    inviter_id: uuid.UUID
    platform_id: uuid.UUID

    model_config = {"extra": "forbid"}


class AdminInviteInDB(AdminInviteBase):
    id: uuid.UUID
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AdminInviteRead(AdminInviteBase):
    id: uuid.UUID
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
