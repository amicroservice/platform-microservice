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
"""

# This module defines the Pydantic models for the `platforms` table, including
# the base model, create/update models, and the model representing a record in the database.

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PlatformBase(BaseModel):
    name: str
    domain_name: str
    properties: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class PlatformCreate(PlatformBase):
    model_config = {"extra": "forbid"}


class PlatformUpdate(BaseModel):
    name: Optional[str] = None
    domain_name: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None

    model_config = {"extra": "forbid"}


class PlatformInDB(PlatformBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class PlatformRead(PlatformBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


def platform_json_schema() -> dict:
    return PlatformRead.model_json_schema()
