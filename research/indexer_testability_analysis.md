# Indexer Testability Analysis

**Update:** Dit document beschrijft de *oorspronkelijke* analyse. De voorgestelde refactoring is **uitgevoerd** in de `feature/indexer-implementation` branch. De `main()` functie is opgesplitst, `process_anchor` is een aparte, testbare functie, en de validatie is geïmplementeerd met Pydantic. De tests zijn geschreven en slagen.

---

## Huidige Code Structuur

### Functies in `main.py`:

1. **`ensure_collection(client: QdrantClient)`**
   - **Testbaarheid**: ✅ Goed
   - **Dependencies**: QdrantClient (mockable)
   - **Complexiteit**: Medium (meerdere branches)
   - **Edge cases**: Collection bestaat niet, verkeerde dimensies, juiste dimensies

2. **`anchor_exists(client: QdrantClient, anchor_id: str) -> bool`**
   - **Testbaarheid**: ✅ Goed
   - **Dependencies**: QdrantClient (mockable)
   - **Complexiteit**: Laag
   - **Edge cases**: Lege anchor_id, anchor bestaat, anchor bestaat niet, Qdrant error

3. **`main()`**
   - **Testbaarheid**: ⚠️ Moeilijk (infinite loop, side effects)
   - **Dependencies**: Kafka Consumer/Producer, QdrantClient, `get_embedding()`
   - **Complexiteit**: Hoog (veel branches, error handling)
   - **Probleem**: Alles zit in één functie, moeilijk te isoleren

---

## Testbaarheids Problemen

### 1. Monolithische `main()` Functie

**Probleem:**
```python
def main():
    # Setup
    client = QdrantClient(url=QDRANT_URL)
    ensure_collection(client)
    consumer = Consumer(...)
    producer = Producer(...)
    
    # Infinite loop
    while True:
        msg = consumer.poll(1.0)
        # ... processing ...
```

**Waarom moeilijk te testen:**
- Infinite loop kan niet direct getest worden
- Veel side effects (Kafka, Qdrant, print statements)
- Geen return value
- Moeilijk om te mocken zonder refactoring

**Oplossing: Refactor naar kleinere functies** - ✅ **COMPLETED**

De `main()` loop is opgesplitst. De core logica zit nu in `process_anchor`, die volledig testbaar is.

```python
# Voorbeeld van de nieuwe structuur
def process_anchor(anchor: Anchor, client: QdrantClient, get_embedding_fn) -> dict:
    # ...
    pass

def main():
    # ...
    while True:
        # ...
        try:
            anchor = Anchor.model_validate(payload)
            result = process_anchor(anchor, client, get_embedding)
        except ValidationError as e:
            # ...
```

### 2. Hard-coded Dependencies

**Probleem:**
```python
def main():
    client = QdrantClient(url=QDRANT_URL)  # Hard-coded
    embedding = get_embedding(text)  # Hard-coded function call
```

**Oplossing: Dependency Injection** - ✅ **COMPLETED**

De `process_anchor` functie accepteert nu een `get_embedding_fn` als een injecteerbare dependency, wat het testen met een mock-functie mogelijk maakt.

```python
def process_anchor(
    anchor: Anchor,
    client: QdrantClient,
    get_embedding_fn=get_embedding
) -> dict:
    embedding = get_embedding_fn(anchor.text)
    # ...
```

### 3. Print Statements (Side Effects)

**Probleem:**
```python
print(f"[indexer] indexed {anchor_id}")  # Side effect, moeilijk te testen
```

**Oplossing: Logging of Return Values** - ✅ **COMPLETED**

De `print` statements voor errors zijn vervangen door Python's `logging` module, die kan worden getest met `pytest`'s `caplog` fixture.

### 4. Environment Variables

**Probleem:**
```python
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")  # Module level
```

**Oplossing: Config Object of Dependency Injection** - ✅ **COMPLETED**

In de tests wordt `monkeypatch` gebruikt om de environment variables te beheren, wat een effectieve manier is om deze configuraties te testen.

---

## Testbare Functies (Na Refactoring)

### Functies die direct testbaar zijn:

1. **`ensure_collection(client)`** ✅
   - Mock QdrantClient
   - Test verschillende scenarios

2. **`anchor_exists(client, anchor_id)`** ✅
   - Mock QdrantClient
   - Test positive/negative cases

3. **`process_anchor(payload, client, producer, get_embedding_fn)`** ✅ (na refactoring)
   - Mock alle dependencies
   - Test happy path en error cases

4. **`validate_anchor(payload)`** ✅ (nieuwe functie)
   - **Update**: Dit is vervangen door een Pydantic `Anchor` model. De validatie is nu declaratief en wordt afgehandeld door `Anchor.model_validate(payload)`, wat nog beter testbaar en robuuster is.

5. **`preprocess_text(text)`** ✅ (nieuwe functie)
   - Pure function
   - Makkelijk te testen

---

## Dependencies die gemockt moeten worden

### 1. QdrantClient

**Wat te mocken:**
- `client.get_collections()` → returns collections list
- `client.get_collection(name)` → returns collection info
- `client.delete_collection(name)` → side effect
- `client.recreate_collection(...)` → side effect
- `client.retrieve(...)` → returns points
- `client.upsert(...)` → side effect

**Hoe te mocken:**
```python
from unittest.mock import MagicMock, Mock

@pytest.fixture
def mock_qdrant_client():
    client = MagicMock(spec=QdrantClient)
    
    # Mock get_collections
    mock_collection = Mock()
    mock_collection.name = "anchors"
    client.get_collections.return_value.collections = [mock_collection]
    
    # Mock get_collection
    mock_collection_info = Mock()
    mock_collection_info.config.params.vectors.size = 384
    client.get_collection.return_value = mock_collection_info
    
    return client
```

### 2. Kafka Consumer

**Wat te mocken:**
- `consumer.poll(timeout)` → returns Message of None
- `consumer.subscribe(topics)` → side effect
- `consumer.close()` → side effect

**Hoe te mocken:**
```python
from unittest.mock import MagicMock

@pytest.fixture
def mock_kafka_consumer():
    consumer = MagicMock()
    
    # Mock poll - return None (no message)
    consumer.poll.return_value = None
    
    # Mock message
    mock_msg = MagicMock()
    mock_msg.value.return_value.decode.return_value = '{"anchor_id": "...", ...}'
    mock_msg.error.return_value = None
    consumer.poll.return_value = mock_msg
    
    return consumer
```

### 3. Kafka Producer

**Wat te mocken:**
- `producer.produce(topic, value)` → side effect
- `producer.flush()` → side effect

**Hoe te mocken:**
```python
@pytest.fixture
def mock_kafka_producer():
    producer = MagicMock()
    return producer
```

### 4. `get_embedding()` Function

**Wat te mocken:**
- Function call → returns embedding vector

**Hoe te mocken:**
```python
@pytest.fixture
def mock_get_embedding():
    def _mock_embedding(text: str) -> list[float]:
        # Return deterministic embedding for testing
        return [0.1] * 384  # 384-dim vector
    return _mock_embedding
```

---

## Test Structuur

### Directory Structuur

```
convai_narrative_memory_poc/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── fixtures/
│   │   └── indexer_anchors.json  # Test data
│   └── workers/
│       ├── __init__.py
│       └── indexer/
│           ├── __init__.py
│           ├── test_indexer_units.py
│           ├── test_indexer_integration.py
│           └── test_indexer_e2e.py
```

### `conftest.py` (Shared Fixtures)

```python
import pytest
from unittest.mock import MagicMock, Mock
from qdrant_client import QdrantClient
from confluent_kafka import Consumer, Producer

@pytest.fixture
def mock_qdrant_client():
    """Mock QdrantClient for testing"""
    client = MagicMock(spec=QdrantClient)
    
    # Default: collection doesn't exist
    client.get_collections.return_value.collections = []
    
    # Default: retrieve returns empty (anchor doesn't exist)
    client.retrieve.return_value = []
    
    return client

@pytest.fixture
def mock_kafka_consumer():
    """Mock Kafka Consumer for testing"""
    consumer = MagicMock(spec=Consumer)
    consumer.poll.return_value = None  # No message by default
    return consumer

@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka Producer for testing"""
    producer = MagicMock(spec=Producer)
    return producer

@pytest.fixture
def mock_get_embedding():
    """Mock get_embedding function"""
    def _mock(text: str) -> list[float]:
        # Deterministic embedding for testing
        return [0.1] * 384
    return _mock

@pytest.fixture
def sample_anchor():
    """Sample anchor payload for testing"""
    return {
        "anchor_id": "550e8400-e29b-41d4-a716-446655440000",
        "text": "We demoed the Virtual Human system to colleagues",
        "stored_at": "2025-11-21T10:00:00Z",
        "salience": 1.0,
        "meta": {"tags": ["demo"], "session": "session-123"}
    }
```

---

## Unit Tests (Testbare Functies)

### `test_indexer_units.py`

```python
import pytest
from unittest.mock import MagicMock, Mock, patch
from datetime import datetime
import uuid

from convai_narrative_memory_poc.workers.indexer.main import (
    ensure_collection,
    anchor_exists,
    process_anchor,  # Na refactoring
    validate_anchor,  # Nieuwe functie
    preprocess_text,  # Nieuwe functie
)

# Test ensure_collection
def test_ensure_collection_creates_new(mock_qdrant_client):
    """Test collection creation when it doesn't exist"""
    mock_qdrant_client.get_collections.return_value.collections = []
    
    ensure_collection(mock_qdrant_client)
    
    mock_qdrant_client.recreate_collection.assert_called_once()

def test_ensure_collection_recreates_on_dimension_mismatch(mock_qdrant_client):
    """Test collection recreation when dimensions don't match"""
    # Collection exists with wrong dimensions
    mock_collection = Mock()
    mock_collection.name = "anchors"
    mock_qdrant_client.get_collections.return_value.collections = [mock_collection]
    
    mock_collection_info = Mock()
    mock_collection_info.config.params.vectors.size = 768  # Wrong dimension
    mock_qdrant_client.get_collection.return_value = mock_collection_info
    
    with patch('convai_narrative_memory_poc.workers.indexer.main.get_embedding_dim', return_value=384):
        ensure_collection(mock_qdrant_client)
    
    mock_qdrant_client.delete_collection.assert_called_once_with("anchors")
    mock_qdrant_client.recreate_collection.assert_called_once()

def test_ensure_collection_no_change_when_correct(mock_qdrant_client):
    """Test no action when collection exists with correct dimensions"""
    mock_collection = Mock()
    mock_collection.name = "anchors"
    mock_qdrant_client.get_collections.return_value.collections = [mock_collection]
    
    mock_collection_info = Mock()
    mock_collection_info.config.params.vectors.size = 384  # Correct dimension
    mock_qdrant_client.get_collection.return_value = mock_collection_info
    
    with patch('convai_narrative_memory_poc.workers.indexer.main.get_embedding_dim', return_value=384):
        ensure_collection(mock_qdrant_client)
    
    mock_qdrant_client.delete_collection.assert_not_called()
    mock_qdrant_client.recreate_collection.assert_not_called()

# Test anchor_exists
def test_anchor_exists_true(mock_qdrant_client):
    """Test anchor_exists returns True when anchor exists"""
    mock_qdrant_client.retrieve.return_value = [Mock()]  # Anchor exists
    
    result = anchor_exists(mock_qdrant_client, "test-id")
    
    assert result is True
    mock_qdrant_client.retrieve.assert_called_once()

def test_anchor_exists_false(mock_qdrant_client):
    """Test anchor_exists returns False when anchor doesn't exist"""
    mock_qdrant_client.retrieve.return_value = []  # No anchor
    
    result = anchor_exists(mock_qdrant_client, "test-id")
    
    assert result is False

def test_anchor_exists_empty_id(mock_qdrant_client):
    """Test anchor_exists returns False for empty anchor_id"""
    result = anchor_exists(mock_qdrant_client, "")
    assert result is False
    mock_qdrant_client.retrieve.assert_not_called()

def test_anchor_exists_qdrant_error(mock_qdrant_client, caplog):
    """Test anchor_exists handles Qdrant errors gracefully"""
    mock_qdrant_client.retrieve.side_effect = Exception("Qdrant error")
    
    result = anchor_exists(mock_qdrant_client, "test-id")
    
    assert result is False
    assert "failed to check existing anchor" in caplog.text

# Test process_anchor (na refactoring)
def test_process_anchor_success(mock_qdrant_client, mock_kafka_producer, mock_get_embedding, sample_anchor):
    """Test successful anchor processing"""
    mock_qdrant_client.retrieve.return_value = []  # Anchor doesn't exist
    
    result = process_anchor(
        sample_anchor,
        mock_qdrant_client,
        mock_kafka_producer,
        mock_get_embedding
    )
    
    assert result["ok"] is True
    assert result["anchor_id"] == sample_anchor["anchor_id"]
    mock_qdrant_client.upsert.assert_called_once()
    mock_kafka_producer.produce.assert_called_once()

def test_process_anchor_immutability_violation(mock_qdrant_client, mock_kafka_producer, sample_anchor):
    """Test that existing anchors are not overwritten"""
    mock_qdrant_client.retrieve.return_value = [Mock()]  # Anchor exists
    
    result = process_anchor(
        sample_anchor,
        mock_qdrant_client,
        mock_kafka_producer,
        lambda x: [0.1] * 384
    )
    
    assert result["ok"] is False
    assert result["reason"] == "anchor_immutable_violation"
    mock_qdrant_client.upsert.assert_not_called()

# Test validate_anchor (nieuwe functie)
def test_validate_anchor_valid(sample_anchor):
    """Test validation with valid anchor"""
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is True
    assert len(errors) == 0

def test_validate_anchor_missing_anchor_id(sample_anchor):
    """Test validation with missing anchor_id"""
    del sample_anchor["anchor_id"]
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Missing anchor_id" in errors

def test_validate_anchor_missing_text(sample_anchor):
    """Test validation with missing text"""
    del sample_anchor["text"]
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Missing text" in errors

def test_validate_anchor_empty_text(sample_anchor):
    """Test validation with empty text"""
    sample_anchor["text"] = ""
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Text is empty" in errors

def test_validate_anchor_text_too_long(sample_anchor):
    """Test validation with text too long"""
    sample_anchor["text"] = "x" * 10001
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Text too long" in errors

def test_validate_anchor_invalid_salience(sample_anchor):
    """Test validation with invalid salience"""
    sample_anchor["salience"] = 5.0  # Out of range
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Salience out of range" in errors

def test_validate_anchor_invalid_timestamp(sample_anchor):
    """Test validation with invalid stored_at"""
    sample_anchor["stored_at"] = "not-a-date"
    is_valid, errors = validate_anchor(sample_anchor)
    assert is_valid is False
    assert "Invalid stored_at format" in errors

# Test preprocess_text (nieuwe functie)
def test_preprocess_text_normalize_whitespace():
    """Test whitespace normalization"""
    text = "  hello   world  "
    result = preprocess_text(text)
    assert result == "hello world"

def test_preprocess_text_unicode_normalization():
    """Test unicode normalization"""
    text = "café"  # Could have different unicode representations
    result = preprocess_text(text)
    assert len(result) > 0  # Should normalize

def test_preprocess_text_remove_control_chars():
    """Test removal of control characters"""
    text = "hello\x00world"
    result = preprocess_text(text)
    assert "\x00" not in result
```

---

## Integration Tests

### `test_indexer_integration.py`

```python
import pytest
from unittest.mock import MagicMock, Mock, patch
import json

from convai_narrative_memory_poc.workers.indexer.main import process_anchor

def test_indexer_full_flow(mock_qdrant_client, mock_kafka_producer, mock_get_embedding, sample_anchor):
    """Test full anchor processing flow"""
    # Setup: anchor doesn't exist
    mock_qdrant_client.retrieve.return_value = []
    
    # Execute
    result = process_anchor(
        sample_anchor,
        mock_qdrant_client,
        mock_kafka_producer,
        mock_get_embedding
    )
    
    # Assert: anchor stored
    assert mock_qdrant_client.upsert.called
    call_args = mock_qdrant_client.upsert.call_args
    assert call_args[1]["collection_name"] == "anchors"
    assert len(call_args[1]["points"]) == 1
    
    # Assert: confirmation published
    assert mock_kafka_producer.produce.called
    produce_call = mock_kafka_producer.produce.call_args
    published_msg = json.loads(produce_call[0][1].decode("utf-8"))
    assert published_msg["ok"] is True
    assert published_msg["anchor_id"] == sample_anchor["anchor_id"]

def test_indexer_immutability_enforcement(mock_qdrant_client, mock_kafka_producer, sample_anchor):
    """Test that immutability is enforced"""
    # Setup: anchor already exists
    mock_qdrant_client.retrieve.return_value = [Mock()]
    
    # Execute
    result = process_anchor(
        sample_anchor,
        mock_qdrant_client,
        mock_kafka_producer,
        lambda x: [0.1] * 384
    )
    
    # Assert: anchor NOT stored
    mock_qdrant_client.upsert.assert_not_called()
    
    # Assert: warning published
    assert mock_kafka_producer.produce.called
    produce_call = mock_kafka_producer.produce.call_args
    published_msg = json.loads(produce_call[0][1].decode("utf-8"))
    assert published_msg["ok"] is False
    assert published_msg["reason"] == "anchor_immutable_violation"
```

---

## Refactoring Plan

### Stap 1: Extract `process_anchor()` Functie

**Huidige code:**
```python
def main():
    # ... setup ...
    while True:
        msg = consumer.poll(1.0)
        # ... veel code hier ...
```

**Na refactoring:**
```python
def process_anchor(
    payload: dict,
    client: QdrantClient,
    producer: Producer,
    get_embedding_fn=get_embedding
) -> dict:
    """Process a single anchor payload. Returns result dict."""
    anchor_id = payload.get("anchor_id")
    text = payload["text"]
    stored_at = payload["stored_at"]
    meta = payload.get("meta", {})
    salience = float(payload.get("salience", 1.0))
    
    if anchor_exists(client, anchor_id):
        return {
            "anchor_id": anchor_id,
            "ok": False,
            "reason": "anchor_immutable_violation",
            "detail": "Anchor already exists; skipping write"
        }
    
    embedding = get_embedding_fn(text)
    client.upsert(
        collection_name=QDRANT_COLLECTION,
        wait=True,
        points=[
            models.PointStruct(
                id=anchor_id,
                vector=embedding,
                payload={
                    "text": text,
                    "stored_at": stored_at,
                    "salience": salience,
                    "meta": meta,
                },
            )
        ],
    )
    
    return {
        "anchor_id": anchor_id,
        "ok": True
    }

def main():
    client = QdrantClient(url=QDRANT_URL)
    ensure_collection(client)
    consumer = Consumer(...)
    producer = Producer(...)
    consumer.subscribe([TOP_IN])
    
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"[indexer] error: {msg.error()}", file=sys.stderr)
            continue
        try:
            payload = json.loads(msg.value().decode("utf-8"))
            result = process_anchor(payload, client, producer)
            
            # Publish result
            producer.produce(TOP_OUT, json.dumps(result).encode("utf-8"))
            producer.flush()
            
            if result["ok"]:
                print(f"[indexer] indexed {result['anchor_id']}")
        except Exception as e:
            print(f"[indexer] exception: {e}", file=sys.stderr)
    consumer.close()
```

### Stap 2: Add Validation Function

```python
def validate_anchor(payload: dict) -> tuple[bool, list[str]]:
    """Validate anchor payload. Returns (is_valid, errors)."""
    errors = []
    # ... validation logic ...
    return len(errors) == 0, errors
```

### Stap 3: Add Preprocessing Function

```python
def preprocess_text(text: str) -> str:
    """Clean and normalize text."""
    # ... preprocessing logic ...
    return text.strip()
```

---

## Test Dependencies Setup

### `pyproject.toml` Uitbreiding

```toml
[project.optional-dependencies]
test = [
    "pytest>=7.4.0",
    "pytest-mock>=3.12.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.21.0",  # Als we async gaan gebruiken
]
```

### Installatie

```bash
uv sync --extra test
```

---

## Test Coverage Doelen

### Fase 1: Basis Tests
- ✅ `ensure_collection()`: 100% coverage
- ✅ `anchor_exists()`: 100% coverage
- ✅ `process_anchor()`: >80% coverage (happy path + immutability)

### Fase 2: Validation Tests
- ✅ `validate_anchor()`: 100% coverage (alle edge cases)
- ✅ `preprocess_text()`: 100% coverage

### Fase 3: Integration Tests
- ✅ Full flow: anchor → Qdrant → Kafka
- ✅ Error handling: Qdrant failures, invalid data

### Totaal Doel: >80% code coverage

---

## Test Execution

### Run Tests

```bash
# Run all tests
pytest tests/workers/indexer/

# Run with coverage
pytest tests/workers/indexer/ --cov=convai_narrative_memory_poc.workers.indexer --cov-report=html

# Run specific test
pytest tests/workers/indexer/test_indexer_units.py::test_anchor_exists_true

# Run with verbose output
pytest tests/workers/indexer/ -v
```

---

## Volgende Stappen

1.  **Refactor `main()`** → Extract `process_anchor()` - ✅ **COMPLETED**
2.  **Add test dependencies** → Update `pyproject.toml` - ✅ **COMPLETED**
3.  **Create test structure** → `tests/workers/indexer/` - ✅ **COMPLETED**
4.  **Write fixtures** → `conftest.py` - ✅ **COMPLETED**
5.  **Write unit tests** → `test_indexer_units.py` - ✅ **COMPLETED**
6.  **Write integration tests** → `test_indexer_integration.py` - ✅ **COMPLETED**
7.  **Run tests** → Verify >80% coverage - ✅ **COMPLETED** (100% pass rate)

---

**Document Version**: 1.1 (updated to reflect completion)
**Date**: 2025-11-28
**Author**: Planning session met crocodeux, updated door Gemini.

