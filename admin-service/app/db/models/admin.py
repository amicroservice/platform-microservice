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

import datetime
import re
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class AdminBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_superadmin: bool = False
    platform_id: Optional[uuid.UUID] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def check_platform_consistency(self):
        # Enforce the same constraint as the DB migration:
        # superadmins must have no platform_id; regular admins must have platform_id
        if self.is_superadmin and self.platform_id is not None:
            raise ValueError("platform_id must be null for superadmins")
        if not self.is_superadmin and self.platform_id is None:
            raise ValueError("platform_id must be provided for non-superadmins")
        return self


class AdminCreate(AdminBase):
    password: str = Field(min_length=8, description="Plain-text password for creation")
    password_confirm: str = Field(
        min_length=8, description="Password confirmation for creation"
    )

    model_config = {"extra": "forbid"}

    @field_validator("password")
    def validate_password(cls, v: str) -> str:
        if v is None:
            raise ValueError("password is required")
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("password must contain at least one special character")
        return v

    @model_validator(mode="after")
    def check_password_confirm(self):
        if self.password != self.password_confirm:
            raise ValueError("password and password_confirm must match")
        return self


class AdminUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_superadmin: Optional[bool] = None
    platform_id: Optional[uuid.UUID] = None
    properties: Optional[Dict[str, Any]] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def partial_platform_consistency(self):
        # Only validate consistency when both fields are provided
        if self.is_superadmin is not None and self.platform_id is not None:
            if self.is_superadmin and self.platform_id is not None:
                raise ValueError("platform_id must be null for superadmins")
            if not self.is_superadmin and self.platform_id is None:
                raise ValueError("platform_id must be provided for non-superadmins")
        return self

    @field_validator("password")
    def validate_password_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("password must contain at least one special character")
        return v


class AdminInDB(AdminBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    password_hash: bytes

    model_config = {"from_attributes": True}


class AdminRead(AdminBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
