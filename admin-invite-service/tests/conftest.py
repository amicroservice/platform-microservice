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

import os
import sys

# Ensure the admin-invite-service directory is on sys.path so `import app` works
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Also add the packaged `app` folder so generated `proto` modules importing
# top-level `proto` can be resolved (they expect `proto` on sys.path).
APP_DIR = os.path.abspath(os.path.join(ROOT, "app"))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Ensure well-known protobuf types are imported so generated `pb2` files
# depending on them can register their descriptors into the pool.
try:
    from google.protobuf import struct_pb2  # noqa: F401
    from google.protobuf import timestamp_pb2  # noqa: F401
except Exception:
    # If protobuf isn't installed in the runtime that runs tests, importing
    # these will fail; tests that require protobuf will error out later.
    pass
