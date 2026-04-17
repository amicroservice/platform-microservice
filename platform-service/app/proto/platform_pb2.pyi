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

class CreateRequest(_message.Message):
    __slots__ = ("name", "domain_name", "properties")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    name: str
    domain_name: str
    properties: _struct_pb2.Struct
    def __init__(self, name: _Optional[str] = ..., domain_name: _Optional[str] = ..., properties: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class CreateResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Platform
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Platform, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class GetRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class GetResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Platform
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Platform, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class UpdateRequest(_message.Message):
    __slots__ = ("id", "name", "domain_name", "properties")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    domain_name: str
    properties: _struct_pb2.Struct
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., domain_name: _Optional[str] = ..., properties: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class UpdateResponse(_message.Message):
    __slots__ = ("success", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: Platform
    error: ValidationError
    def __init__(self, success: _Optional[_Union[Platform, _Mapping]] = ..., error: _Optional[_Union[ValidationError, _Mapping]] = ...) -> None: ...

class ListRequest(_message.Message):
    __slots__ = ("order_by", "limit", "offset", "filters")
    class FiltersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    order_by: str
    limit: int
    offset: int
    filters: _containers.ScalarMap[str, str]
    def __init__(self, order_by: _Optional[str] = ..., limit: _Optional[int] = ..., offset: _Optional[int] = ..., filters: _Optional[_Mapping[str, str]] = ...) -> None: ...

class Platform(_message.Message):
    __slots__ = ("id", "created_at", "updated_at", "name", "domain_name", "properties")
    ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    id: str
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    name: str
    domain_name: str
    properties: _struct_pb2.Struct
    def __init__(self, id: _Optional[str] = ..., created_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., name: _Optional[str] = ..., domain_name: _Optional[str] = ..., properties: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

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
