"""Shared constants for the MVP integration tests.

Container images and timeouts used by both the relay and the Temporal tests.
"""

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.2.3"
READ_SECONDS = 30
