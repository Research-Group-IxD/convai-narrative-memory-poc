import os, json, time, sys, datetime as dt, logging
from uuid import UUID
from pydantic import BaseModel, Field, ValidationError
from confluent_kafka import Consumer, Producer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from convai_narrative_memory_poc.workers.common.utils import (
    QDRANT_URL,
    QDRANT_COLLECTION,
    KAFKA_BOOTSTRAP,
    get_embedding,
    get_embedding_dim,
)

TOP_IN = "anchors-write"
TOP_OUT = "anchors-indexed"


class Anchor(BaseModel):
    anchor_id: UUID
    text: str = Field(..., min_length=1, max_length=10000)
    stored_at: dt.datetime
    salience: float = Field(default=1.0, ge=0.3, le=2.5)
    meta: dict = Field(default_factory=dict)


def ensure_collection(client: QdrantClient):
    dim = get_embedding_dim()
    cols = client.get_collections().collections
    names = [c.name for c in cols]

    # Check if collection exists and has correct dimensions
    if QDRANT_COLLECTION in names:
        collection_info = client.get_collection(QDRANT_COLLECTION)
        if collection_info.config.params.vectors.size != dim:
            print(
                f"[indexer] Collection has wrong dimensions ({collection_info.config.params.vectors.size} vs {dim}), recreating..."
            )
            client.delete_collection(QDRANT_COLLECTION)
            names.remove(QDRANT_COLLECTION)

    if QDRANT_COLLECTION not in names:
        print(
            f"[indexer] Creating collection with {dim} dimensions for {os.getenv('EMBEDDING_MODEL', 'deterministic')} embeddings"
        )
        client.recreate_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=models.VectorParams(
                size=dim, distance=models.Distance.COSINE
            ),
        )


def anchor_exists(client: QdrantClient, anchor_id: str) -> bool:
    if not anchor_id:
        return False
    try:
        existing = client.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=[anchor_id],
            with_payload=False,
            with_vectors=False,
        )
        return bool(existing)
    except Exception as e:
        logging.error(f"failed to check existing anchor {anchor_id}: {e}")
        return False


def process_anchor(
    anchor: Anchor,
    client: QdrantClient,
    get_embedding_fn=get_embedding,
) -> dict:
    """Process a single anchor payload. Returns result dict."""
    anchor_id_str = str(anchor.anchor_id)
    if anchor_exists(client, anchor_id_str):
        return {
            "anchor_id": anchor_id_str,
            "ok": False,
            "reason": "anchor_immutable_violation",
            "detail": "Anchor already exists; skipping write",
        }

    embedding = get_embedding_fn(anchor.text)
    client.upsert(
        collection_name=QDRANT_COLLECTION,
        wait=True,
        points=[
            models.PointStruct(
                id=anchor_id_str,
                vector=embedding,
                payload={
                    "text": anchor.text,
                    "stored_at": anchor.stored_at.isoformat(),
                    "salience": anchor.salience,
                    "meta": anchor.meta,
                },
            )
        ],
    )

    return {"anchor_id": anchor_id_str, "ok": True}


def main():
    client = QdrantClient(url=QDRANT_URL)
    ensure_collection(client)
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": "indexer",
            "auto.offset.reset": "earliest",
        }
    )
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})
    consumer.subscribe([TOP_IN])
    print("[indexer] listening...")
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"[indexer] error: {msg.error()}", file=sys.stderr)
            continue
        
        payload_str = msg.value().decode("utf-8")
        try:
            payload = json.loads(payload_str)
            anchor = Anchor.model_validate(payload)
            result = process_anchor(anchor, client, get_embedding)

            # Publish result
            producer.produce(TOP_OUT, json.dumps(result).encode("utf-8"))
            producer.flush()

            if result["ok"]:
                print(f"[indexer] indexed {result['anchor_id']}")
            else:
                print(
                    f"[indexer] WARNING: {result['reason']} for anchor {result['anchor_id']}",
                    file=sys.stderr,
                )
        except ValidationError as e:
            payload = json.loads(payload_str)
            error_msg = {
                "anchor_id": payload.get("anchor_id", "unknown"),
                "ok": False,
                "reason": "validation_failed",
                "errors": e.errors(),
            }
            producer.produce(TOP_OUT, json.dumps(error_msg).encode("utf-8"))
            producer.flush()
            print(f"[indexer] Validation failed for anchor {payload.get('anchor_id', 'unknown')}: {e.errors()}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"[indexer] exception: {e}", file=sys.stderr)
    consumer.close()


if __name__ == "__main__":
    main()
