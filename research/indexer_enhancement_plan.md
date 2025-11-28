# Indexer Worker Enhancement Plan

## Huidige Status Analyse

### Wat de Indexer worker nu doet:

**Core Functionaliteit:**
1. **Input**: Consumeert `anchors-write` topic met:
   - `anchor_id` (UUID)
   - `text` (memory text)
   - `stored_at` (ISO timestamp)
   - `salience` (importance weight, default 1.0)
   - `meta` (optional metadata: tags, session, etc.)

2. **Processing Pipeline**:
   - Check if anchor already exists (immutability enforcement)
   - Generate embedding from text (via `get_embedding()`)
   - Store in Qdrant with:
     - Vector (embedding)
     - Payload (text, stored_at, salience, meta)
   - Publish confirmation to `anchors-indexed`

3. **Collection Management**:
   - On startup: check collection dimensions
   - If dimensions don't match embedding model → recreate collection
   - Auto-create collection if it doesn't exist

### Huidige Features:

✅ **Immutability enforcement**: Prevents overwriting existing anchors  
✅ **Auto dimension handling**: Recreates collection when model changes  
✅ **Multi-embedding support**: Deterministic, Nomic, MXBai, BGE-M3  
✅ **Error handling**: Basic try/catch with logging  
✅ **Stateless design**: Can scale horizontally

### Wat ontbreekt (uit research proposal & code analyse):

❌ **Emotion detection**: Automatische detectie van emotie bij anchor creation  
❌ **Automatic salience calculation**: Salience wordt nu handmatig gegeven  
✅ **Input validation**: Geïmplementeerd met Pydantic voor robuuste validatie (was ❌)
❌ **Batch processing**: Verwerkt één anchor per keer (inefficiënt bij hoge load)  
❌ **Multi-agent support**: Geen `agent_id` in metadata handling  
❌ **Metrics/monitoring**: Geen metrics over processing time, success rate, etc.  
❌ **Retry logic**: Geen retry bij Qdrant failures  
❌ **Duplicate detection**: Alleen op `anchor_id`, niet op text similarity  
❌ **Text preprocessing**: Geen cleaning/normalization van text  
❌ **Embedding caching**: Herhaalde embeddings worden opnieuw berekend

---

## Enhancement Doelstellingen

### 1. Emotion Detection (Priority: HIGH - uit research proposal)

**Wat het moet doen:**
- Detecteert automatisch emotie in anchor text
- Voegt emotion metadata toe aan anchor
- Ondersteunt mood-aware retrieval in Resonance

**Implementatie Opties:**

**Optie A: LLM-based (nauwkeurig, maar langzaam)**
```python
def detect_emotion_llm(text: str) -> dict:
    """Use LLM to detect emotion"""
    prompt = f"""
    Analyze the emotional content of this text and return JSON:
    {{
        "valence": -0.8,  # -1.0 (negative) to 1.0 (positive)
        "arousal": 0.9,   # 0.0 (calm) to 1.0 (excited)
        "dominance": 0.3  # 0.0 (powerless) to 1.0 (powerful)
    }}
    
    Text: {text}
    """
    # Call Ollama/OpenAI
    response = call_llm(prompt)
    return json.loads(response)
```

**Optie B: Rule-based (snel, maar minder nauwkeurig)**
```python
def detect_emotion_rules(text: str) -> dict:
    """Use keyword matching for emotion detection"""
    positive_words = ["happy", "excited", "great", "wonderful"]
    negative_words = ["sad", "angry", "frustrated", "disappointed"]
    high_arousal = ["urgent", "critical", "emergency", "crisis"]
    
    text_lower = text.lower()
    valence = 0.0
    if any(word in text_lower for word in positive_words):
        valence = 0.5
    if any(word in text_lower for word in negative_words):
        valence = -0.5
    
    arousal = 0.5
    if any(word in text_lower for word in high_arousal):
        arousal = 0.9
    
    return {
        "valence": valence,
        "arousal": arousal,
        "dominance": 0.5  # Default
    }
```

**Optie C: Hybrid (LLM voor belangrijke, rules voor rest)**
```python
def detect_emotion(text: str, salience: float) -> dict:
    """Use LLM for high-salience, rules for low-salience"""
    if salience >= 1.5:  # Important memories
        return detect_emotion_llm(text)
    else:
        return detect_emotion_rules(text)
```

**Data Structure:**
```python
# Anchor payload uitbreiding:
{
    "text": "...",
    "stored_at": "...",
    "salience": 1.0,
    "emotion": {  # NIEUW
        "valence": -0.8,
        "arousal": 0.9,
        "dominance": 0.3,
        "detected_at": "2025-11-21T10:00:00Z",
        "method": "llm" | "rules" | "hybrid"
    },
    "meta": {...}
}
```

### 2. Automatic Salience Calculation (Priority: MEDIUM)

**Wat het moet doen:**
- Berekent automatisch salience als deze niet wordt gegeven
- Gebruikt heuristics: keywords, text length, emotional intensity

**Implementatie:**
```python
def calculate_salience(text: str, emotion: dict = None) -> float:
    """Calculate salience based on text characteristics"""
    base_salience = 1.0
    
    # Length factor (longer = more important, up to a point)
    word_count = len(text.split())
    if word_count > 50:
        base_salience += 0.2
    elif word_count < 10:
        base_salience -= 0.2
    
    # Keyword-based (critical events)
    critical_keywords = ["critical", "urgent", "emergency", "outage", "crisis"]
    if any(kw in text.lower() for kw in critical_keywords):
        base_salience += 1.0
    
    # Emotion-based (high arousal = higher salience)
    if emotion:
        arousal = emotion.get("arousal", 0.5)
        base_salience += (arousal - 0.5) * 0.5  # -0.25 to +0.25
    
    # Question marks (questions might be less important)
    if text.endswith("?"):
        base_salience -= 0.1
    
    # Clamp to valid range
    return max(0.3, min(2.5, base_salience))
```

**Usage:**
```python
# In main():
salience = float(payload.get("salience"))
if salience is None or salience == 1.0:  # Default or not provided
    emotion = detect_emotion(text) if ENABLE_EMOTION else None
    salience = calculate_salience(text, emotion)
```

### 3. Input Validation (Priority: HIGH) - ✅ COMPLETED

**Wat het doet:**
- Valideert anchor data met Pydantic voordat processing start.
- Voorkomt automatisch invalid data in Qdrant.
- Geeft duidelijke, gestructureerde error messages bij validatiefouten.

**Implementatie:**
De validatie wordt nu direct afgehandeld door een Pydantic `BaseModel`. Dit is robuuster en onderhoudbaarder dan een handmatige validatiefunctie.

```python
# In main.py
from pydantic import BaseModel, Field, ValidationError
from uuid import UUID
import datetime as dt

class Anchor(BaseModel):
    anchor_id: UUID
    text: str = Field(..., min_length=1, max_length=10000)
    stored_at: dt.datetime
    salience: float = Field(default=1.0, ge=0.3, le=2.5)
    meta: dict = Field(default_factory=dict)

# In de main loop:
try:
    payload = json.loads(msg.value().decode("utf-8"))
    anchor = Anchor.model_validate(payload) # Automatische validatie
    # ...
except ValidationError as e:
    # Handel validatiefouten af
    # ...
```

Deze aanpak vervangt de noodzaak voor een aparte `validate_anchor` functie en biedt een sterkere garantie voor datakwaliteit.

### 4. Batch Processing (Priority: MEDIUM)

**Wat het moet doen:**
- Verwerkt meerdere anchors in één batch
- Efficiënter bij hoge load
- Reduceert Qdrant round-trips

**Implementatie:**
```python
BATCH_SIZE = int(os.getenv("INDEXER_BATCH_SIZE", "10"))
BATCH_TIMEOUT = float(os.getenv("INDEXER_BATCH_TIMEOUT", "1.0"))  # seconds

def main():
    # ... setup ...
    batch = []
    last_batch_time = time.time()
    
    while True:
        msg = consumer.poll(0.1)  # Shorter timeout for batching
        if msg is None:
            # Check if we should flush batch
            if batch and (time.time() - last_batch_time) > BATCH_TIMEOUT:
                process_batch(batch, client, producer)
                batch = []
                last_batch_time = time.time()
            continue
        
        # ... error handling ...
        
        payload = json.loads(msg.value().decode("utf-8"))
        batch.append(payload)
        
        if len(batch) >= BATCH_SIZE:
            process_batch(batch, client, producer)
            batch = []
            last_batch_time = time.time()

def process_batch(batch: list, client: QdrantClient, producer: Producer):
    """Process multiple anchors in one batch"""
    points = []
    for payload in batch:
        # ... validation, embedding generation ...
        points.append(models.PointStruct(...))
    
    # Single Qdrant upsert for all points
    client.upsert(
        collection_name=QDRANT_COLLECTION,
        wait=True,
        points=points
    )
    
    # Publish confirmations
    for payload in batch:
        out = {"anchor_id": payload["anchor_id"], "ok": True}
        producer.produce(TOP_OUT, json.dumps(out).encode("utf-8"))
    producer.flush()
```

### 5. Multi-Agent Support (Priority: MEDIUM)

**Wat het moet doen:**
- Ondersteunt `agent_id` in metadata
- Validates agent ownership
- Foundation voor multi-agent features in Resonance

**Implementatie:**
```python
# In anchor payload:
{
    "meta": {
        "agent_id": "agent-123",  # NIEUW
        "visibility": "private" | "shared" | "public",  # NIEUW
        "shared_with": ["agent-456"],  # NIEUW (als shared)
        "tags": [...],
        "session": "..."
    }
}

# Validation:
def validate_agent_context(payload: dict) -> tuple[bool, str]:
    """Validate agent_id and visibility settings"""
    meta = payload.get("meta", {})
    agent_id = meta.get("agent_id")
    visibility = meta.get("visibility", "private")
    
    if visibility == "shared":
        shared_with = meta.get("shared_with", [])
        if not shared_with:
            return False, "shared visibility requires shared_with list"
    
    return True, ""
```

### 6. Metrics & Monitoring (Priority: LOW)

**Wat het moet doen:**
- Tracks processing time per anchor
- Tracks success/failure rates
- Tracks embedding generation time
- Exports metrics (Prometheus, statsd, etc.)

**Implementatie:**
```python
import time
from collections import defaultdict

_metrics = {
    "anchors_processed": 0,
    "anchors_failed": 0,
    "embedding_time_total": 0.0,
    "qdrant_time_total": 0.0,
    "validation_failures": defaultdict(int)
}

def record_metric(name: str, value: float = 1.0):
    """Record a metric"""
    if name in _metrics:
        if isinstance(_metrics[name], (int, float)):
            _metrics[name] += value
        else:
            _metrics[name][value] += 1

# In main():
start_time = time.time()
embedding = get_embedding(text)
embedding_time = time.time() - start_time
record_metric("embedding_time_total", embedding_time)
record_metric("anchors_processed")

# Periodic export (every 60 seconds)
def export_metrics():
    # Export to Prometheus, statsd, or log
    pass
```

### 7. Retry Logic (Priority: MEDIUM)

**Wat het moet doen:**
- Retry bij Qdrant failures
- Exponential backoff
- Dead letter queue voor permanent failures

**Implementatie:**
```python
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds

def upsert_with_retry(client, collection, points, max_retries=MAX_RETRIES):
    """Upsert with retry logic"""
    for attempt in range(max_retries):
        try:
            client.upsert(
                collection_name=collection,
                wait=True,
                points=points
            )
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                raise  # Last attempt, raise exception
            delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
            time.sleep(delay)
            print(f"[indexer] Retry {attempt + 1}/{max_retries} after {delay}s")
    return False
```

### 8. Text Preprocessing (Priority: LOW)

**Wat het moet doen:**
- Normaliseert text (whitespace, encoding)
- Optioneel: removes stopwords, lemmatization
- Consistent text format

**Implementatie:**
```python
def preprocess_text(text: str) -> str:
    """Clean and normalize text"""
    # Remove extra whitespace
    text = " ".join(text.split())
    
    # Normalize unicode
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    
    # Remove control characters
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    
    return text.strip()

# In main():
text = preprocess_text(payload["text"])
```

### 9. Embedding Caching (Priority: LOW)

**Wat het moet doen:**
- Cache embeddings voor identieke text
- Reduceert redundant calculations
- Memory-efficient (LRU cache)

**Implementatie:**
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_cached_embedding(text: str) -> list[float]:
    """Get embedding with caching"""
    return get_embedding(text)

# In main():
embedding = get_cached_embedding(text)
```

---

## Implementatie Volgorde

### Fase 1: Test Infrastructure (Week 1) - ✅ COMPLETED

**Status:** De testinfrastructuur is volledig opgezet. Unit en integratietests zijn geschreven voor de bestaande functionaliteit en de code is gerefactored om testbaarheid te verbeteren. De test-suite draait succesvol.

**Wat we hebben gemaakt:**

1.  **Unit Tests** (`tests/workers/indexer/test_indexer_units.py`):
    - Tests voor `process_anchor`, `ensure_collection`, en `anchor_exists`.
2.  **Integration Tests** (`tests/workers/indexer/test_indexer_integration.py`):
    - Tests voor de volledige `process_anchor` flow met gemockte dependencies.
3.  **Test Data Fixtures** (`tests/conftest.py`):
    - Gedeelde fixtures voor Qdrant, Kafka, en Pydantic modellen.

---

### Fase 2: Input Validation (Week 2) - ✅ COMPLETED

**Status:** Input validatie is geïmplementeerd met Pydantic, wat de oorspronkelijke planning overtreft in robuustheid. De `main` loop vangt `ValidationError` exceptions af en rapporteert deze.

---

### Fase 3: Emotion Detection (Week 3-4)

**Stap 3.1: Choose Implementation**
- Beslissen: LLM-based, rule-based, of hybrid?
- Trade-off: accuracy vs. speed vs. cost

**Stap 3.2: Implementation**
- Implement gekozen approach
- Add emotion to anchor payload
- Test accuracy (human evaluation)

**Stap 3.3: Integration**
- Integreer in main processing flow
- Optioneel: feature flag (`ENABLE_EMOTION_DETECTION`)
- Backward compatible (geen emotion = OK)

---

### Fase 4: Automatic Salience (Week 5)

**Stap 4.1: Heuristics Design**
- Test verschillende heuristics
- Calibrate met bestaande anchors
- Validate met human evaluation

**Stap 4.2: Implementation**
- Implement `calculate_salience()`
- Integreer met emotion detection
- Optioneel: feature flag

---

### Fase 5: Multi-Agent Support (Week 6)

**Stap 5.1: Data Structure**
- Add `agent_id` to metadata
- Add `visibility` field
- Update validation

**Stap 5.2: Integration**
- Validate agent context
- Store in Qdrant
- Foundation voor Resonance multi-agent filtering

---

### Fase 6: Performance (Week 7)

**Stap 6.1: Batch Processing**
- Implement batch collection
- Test performance improvement
- Tune batch size

**Stap 6.2: Caching**
- Embedding cache
- Test memory usage
- Tune cache size

**Stap 6.3: Retry Logic**
- Implement retry with backoff
- Test failure scenarios
- Dead letter queue

---

## Test Strategie

### Test Pyramid

```
        /\
       /  \      E2E Tests (1-2)
      /____\
     /      \    Integration Tests (5-10)
    /________\
   /          \  Unit Tests (15-20)
  /____________\
```

### Unit Tests (Bottom Layer)

```python
# test_indexer_units.py

def test_anchor_exists_true():
    """Test anchor_exists returns True for existing anchor"""
    # Mock Qdrant client
    # Test positive case

def test_anchor_exists_false():
    """Test anchor_exists returns False for non-existent anchor"""
    # Mock Qdrant client
    # Test negative case

def test_ensure_collection_dimension_mismatch():
    """Test collection recreation when dimensions don't match"""
    # Mock Qdrant client
    # Test dimension mismatch scenario

def test_validate_anchor_valid():
    """Test validation with valid anchor"""
    anchor = {"anchor_id": "...", "text": "...", "stored_at": "..."}
    is_valid, errors = validate_anchor(anchor)
    assert is_valid
    assert len(errors) == 0

def test_validate_anchor_missing_fields():
    """Test validation with missing required fields"""
    anchor = {"text": "..."}  # Missing anchor_id, stored_at
    is_valid, errors = validate_anchor(anchor)
    assert not is_valid
    assert "Missing anchor_id" in errors

def test_validate_anchor_invalid_salience():
    """Test validation with invalid salience"""
    anchor = {"salience": 5.0}  # Out of range
    is_valid, errors = validate_anchor(anchor)
    assert not is_valid
    assert "Salience out of range" in errors
```

### Integration Tests (Middle Layer)

```python
# test_indexer_integration.py

def test_indexer_kafka_flow(mock_qdrant, mock_kafka):
    """Test full Kafka consumer → processing → producer flow"""
    # Setup: mock Qdrant
    # Setup: mock Kafka consumer with test anchor
    # Execute: run indexer main loop
    # Assert: verify anchor stored in Qdrant
    # Assert: verify confirmation published

def test_indexer_immutability():
    """Test that existing anchors are not overwritten"""
    # Create anchor
    # Try to create again with same anchor_id
    # Verify warning published
    # Verify anchor not overwritten

def test_indexer_collection_recreation():
    """Test collection recreation on dimension mismatch"""
    # Setup collection with wrong dimensions
    # Start indexer
    # Verify collection recreated
```

### E2E Tests (Top Layer)

```python
# test_indexer_e2e.py

def test_full_anchor_lifecycle():
    """Test: anchor creation → storage → retrieval"""
    # 1. Create anchor via indexer
    # 2. Verify stored in Qdrant
    # 3. Verify can be retrieved
```

---

## File Structure

```
convai_narrative_memory_poc/
├── workers/
│   └── indexer/
│       ├── main.py                    # Huidige implementatie met Pydantic model
│       ├── emotion.py                # NIEUW: Emotion detection
│       ├── salience.py               # NIEUW: Salience calculation
│       ├── preprocessing.py           # NIEUW: Text preprocessing
│       └── metrics.py                # NIEUW: Metrics tracking
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   └── indexer_anchors.json
│   └── workers/
│       └── indexer/
│           ├── test_indexer_units.py
│           └── test_indexer_integration.py
└── research/
    └── indexer_enhancement_plan.md   # Dit document
```

---

## Success Criteria

### Fase 1 (Tests):
- ✅ >80% code coverage voor indexer (behaald, gecheckt met `pytest-cov`)
- ✅ Alle edge cases hebben tests
- ✅ Tests kunnen draaien zonder Docker/Kafka (mocked)

### Fase 2 (Validation):
- ✅ Invalid anchors worden afgewezen (afgehandeld door Pydantic)
- ✅ Error messages zijn duidelijk (Pydantic `ValidationError`)
- ✅ Backward compatible

### Fase 3 (Emotion):
- ✅ Emotion detection accuracy >70% (human evaluation)
- ✅ Processing time increase <20%
- ✅ Backward compatible (geen emotion = OK)

### Fase 4 (Salience):
- ✅ Auto-calculated salience correlates with manual (r > 0.6)
- ✅ Processing time increase <10%

### Fase 5 (Multi-Agent):
- ✅ Agent metadata wordt correct opgeslagen
- ✅ Validation werkt correct

### Fase 6 (Performance):
- ✅ Batch processing reduces Qdrant calls by 80%+
- ✅ Caching reduces embedding calculations by 50%+
- ✅ Retry logic handles transient failures

---

## Risico's & Mitigatie

| Risico | Impact | Mitigatie |
|--------|--------|-----------|
| Emotion detection te traag | Medium | Use hybrid approach, feature flag |
| Auto salience te onnauwkeurig | Medium | Allow manual override, calibration |
| Batch processing complexiteit | Low | Start small (batch_size=5), increment |
| Validation te strict | Medium | Feature flag, backward compatible |

---

## Volgende Stappen

1. **Review dit plan** met team (Lonn, Coen)
2. **Beslissen**: Starten met tests of direct features?
3. **Vergelijken met andere workers**: Welke eerst?
4. **Setup test infrastructure**: pytest, fixtures, CI/CD
5. **Begin met Fase 1**: Unit tests voor bestaande functies

---

## Vergelijking: Indexer vs. Andere Workers

| Aspect | Indexer | Resonance | Reteller |
|--------|---------|-----------|----------|
| **Complexiteit** | Laag-Medium | Hoog | Hoog |
| **Testbaarheid** | Goed (deterministic) | Goed (deterministic) | Moeilijker (LLM) |
| **Impact** | Hoog (data integrity) | Hoog (retrieval) | Hoog (output) |
| **Dependencies** | Qdrant, Embeddings | Qdrant, Embeddings | LLM APIs |
| **Performance kritiek** | Medium (write latency) | Hoog (query latency) | Laag (async) |

**Aanbeveling**: Indexer is goed om mee te beginnen omdat:
- Relatief simpel (goede learning curve)
- Kritiek voor data integrity (goede test practice)
- Foundation voor andere features (emotion, multi-agent)

---

**Document Version**: 1.0  
**Date**: 2025-11-21  
**Author**: Planning session met crocodeux

