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

# Use the official Python image from the Docker Hub
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt file into the container
COPY requirements.txt .

# Install grpcurl using `go install` to avoid brittle release asset names
RUN set -eux; \
	apt-get update; \
	apt-get install -y --no-install-recommends ca-certificates golang-go; \
	export GOBIN=/usr/local/bin; \
	export GOPATH=/go; \
	go install github.com/fullstorydev/grpcurl/cmd/grpcurl@latest; \
	rm -rf /var/lib/apt/lists/*;

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --upgrade pip

# Copy the rest of the application code into the container
COPY . .

# Expose gRPC and metrics ports
EXPOSE 50051
EXPOSE 8000

# Define the command to run your app
CMD ["python", "app/server.py"]
