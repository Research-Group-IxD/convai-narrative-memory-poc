"""
Shared pytest fixtures for all tests.
"""
import pytest
from unittest.mock import MagicMock, Mock
from qdrant_client import QdrantClient
from confluent_kafka import Consumer, Producer
import uuid
from convai_narrative_memory_poc.workers.indexer.main import Anchor


@pytest.fixture
def mock_qdrant_client():
    """Mock QdrantClient for testing."""
    client = MagicMock(spec=QdrantClient)

    # Default: collection doesn't exist
    client.get_collections.return_value.collections = []

    # Default: retrieve returns empty (anchor doesn't exist)
    client.retrieve.return_value = []

    return client


@pytest.fixture
def mock_kafka_consumer():
    """Mock Kafka Consumer for testing."""
    consumer = MagicMock(spec=Consumer)
    consumer.poll.return_value = None  # No message by default
    return consumer


@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka Producer for testing."""
    producer = MagicMock(spec=Producer)
    return producer


@pytest.fixture
def mock_get_embedding():
    """Mock get_embedding function that returns deterministic embeddings."""

    def _mock(text: str) -> list[float]:
        # Return deterministic embedding for testing (384-dim)
        return [0.1] * 384

    return _mock


@pytest.fixture
def sample_anchor_payload():
    """Sample anchor payload as a dictionary for testing."""
    return {
        "anchor_id": str(uuid.uuid4()),
        "text": "We demoed the Virtual Human system to colleagues",
        "stored_at": "2025-11-21T10:00:00Z",
        "salience": 1.0,
        "meta": {"tags": ["demo"], "session": "session-123"},
    }


@pytest.fixture
def sample_anchor(sample_anchor_payload):
    """Sample anchor as a Pydantic model instance."""
    return Anchor.model_validate(sample_anchor_payload)
