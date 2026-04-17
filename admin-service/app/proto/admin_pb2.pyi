from typing import (
    ClassVar as _ClassVar,
    Iterable as _Iterable,
    Mapping as _Mapping,
    Optional as _Optional,
    Union as _Union,
)

from google.protobuf import (
    descriptor as _descriptor,
    message as _message,
    struct_pb2 as _struct_pb2,
    timestamp_pb2 as _timestamp_pb2,
)
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class RegisterRequest(_message.Message):
    __slots__ = ("email", "password", "password_confirm", "first_name", "last_name", "properties", "platform_id")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_CONFIRM_FIELD_NUMBER: _ClassVar[int]
    FIRST_NAME_FIELD_NUMBER: _ClassVar[int]
    LAST_NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    email: str
    password: str
    password_confirm: str
    first_name: str
    last_name: str
    properties: _struct_pb2.Struct
    platform_id: str
    def __init__(self, email: _Optional[str] = ..., password: _Optional[str] = ..., password_confirm: _Optional[str] = ..., first_name: _Optional[str] = ..., last_name: _Optional[str] = ..., properties: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., platform_id: _Optional[str] = ...) -> None: ...

class RegisterResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Admin
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Admin, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class LoginResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: AdminToken
    error: ValidationError
    def __init__(self, success: _Optional[_Union[AdminToken, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class GetResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Admin
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Admin, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class UpdateResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Admin
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Admin, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class Admin(_message.Message):
    __slots__ = ("id", "created_at", "updated_at", "email", "first_name", "last_name", "properties", "is_active", "is_superadmin", "platform_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    FIRST_NAME_FIELD_NUMBER: _ClassVar[int]
    LAST_NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    IS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    IS_SUPERADMIN_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    email: str
    first_name: str
    last_name: str
    properties: _struct_pb2.Struct
    is_active: bool
    is_superadmin: bool
    platform_id: str
    def __init__(self, id: _Optional[str] = ..., created_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., email: _Optional[str] = ..., first_name: _Optional[str] = ..., last_name: _Optional[str] = ..., properties: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., is_active: bool = ..., is_superadmin: bool = ..., platform_id: _Optional[str] = ...) -> None: ...

class LoginRequest(_message.Message):
    __slots__ = ("email", "password", "platform_id")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    email: str
    password: str
    platform_id: str
    def __init__(self, email: _Optional[str] = ..., password: _Optional[str] = ..., platform_id: _Optional[str] = ...) -> None: ...

class AdminToken(_message.Message):
    __slots__ = ("token",)
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    token: str
    def __init__(self, token: _Optional[str] = ...) -> None: ...

class GetRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class UpdateRequest(_message.Message):
    __slots__ = ("id", "email", "password", "password_confirm", "first_name", "last_name", "is_superadmin", "is_active")
    ID_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_CONFIRM_FIELD_NUMBER: _ClassVar[int]
    FIRST_NAME_FIELD_NUMBER: _ClassVar[int]
    LAST_NAME_FIELD_NUMBER: _ClassVar[int]
    IS_SUPERADMIN_FIELD_NUMBER: _ClassVar[int]
    IS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    id: str
    email: str
    password: str
    password_confirm: str
    first_name: str
    last_name: str
    is_superadmin: bool
    is_active: bool
    def __init__(self, id: _Optional[str] = ..., email: _Optional[str] = ..., password: _Optional[str] = ..., password_confirm: _Optional[str] = ..., first_name: _Optional[str] = ..., last_name: _Optional[str] = ..., is_superadmin: bool = ..., is_active: bool = ...) -> None: ...

class ListRequest(_message.Message):
    __slots__ = ("order_by", "limit", "offset", "filters", "property_filters", "property_in_filters")
    class FiltersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class PropertyFiltersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class PropertyInFiltersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: StringList
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[StringList, _Mapping]] = ...) -> None: ...
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    PROPERTY_FILTERS_FIELD_NUMBER: _ClassVar[int]
    PROPERTY_IN_FILTERS_FIELD_NUMBER: _ClassVar[int]
    order_by: str
    limit: int
    offset: int
    filters: _containers.ScalarMap[str, str]
    property_filters: _containers.ScalarMap[str, str]
    property_in_filters: _containers.MessageMap[str, StringList]
    def __init__(self, order_by: _Optional[str] = ..., limit: _Optional[int] = ..., offset: _Optional[int] = ..., filters: _Optional[_Mapping[str, str]] = ..., property_filters: _Optional[_Mapping[str, str]] = ..., property_in_filters: _Optional[_Mapping[str, StringList]] = ...) -> None: ...

class StringList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, values: _Optional[_Iterable[str]] = ...) -> None: ...

class ValidationError(_message.Message):
    __slots__ = ("field_errors", "message")
    FIELD_ERRORS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    field_errors: _containers.RepeatedCompositeFieldContainer[FieldError]
    message: str
    def __init__(self, field_errors: _Optional[_Iterable[_Union[FieldError, _Mapping]]] = ..., message: _Optional[str] = ...) -> None: ...

class FieldError(_message.Message):
    __slots__ = ("field", "code", "message")
    FIELD_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    field: str
    code: str
    message: str
    def __init__(self, field: _Optional[str] = ..., code: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...
