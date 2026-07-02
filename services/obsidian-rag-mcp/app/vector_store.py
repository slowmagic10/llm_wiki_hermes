import math
from typing import Any

from app.config import settings


_collection_cache: Any | None = None


def vector_backend_name() -> str:
    return settings.vector_backend


def milvus_enabled() -> bool:
    return settings.vector_backend == "milvus"


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 0:
        return [float(value) for value in values]
    return [float(value) / norm for value in values]


def _collection(dim: int | None = None):
    global _collection_cache
    if _collection_cache is not None:
        return _collection_cache

    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    connections.connect(alias="default", uri=settings.milvus_uri)
    name = settings.milvus_collection
    if not utility.has_collection(name):
        if not dim:
            raise ValueError("Milvus collection does not exist and vector dim is unknown")
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="path", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="LLM Wiki chunk embeddings")
        collection = Collection(name=name, schema=schema)
        collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": "HNSW",
                "metric_type": "IP",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
    else:
        collection = Collection(name=name)
    collection.load()
    _collection_cache = collection
    return collection


def ping_milvus() -> dict[str, Any]:
    from pymilvus import Collection, connections, utility

    connections.connect(alias="default", uri=settings.milvus_uri)
    exists = utility.has_collection(settings.milvus_collection)
    count = None
    if exists:
        collection = Collection(settings.milvus_collection)
        collection.load()
        count = collection.num_entities
    return {
        "uri": settings.milvus_uri,
        "collection": settings.milvus_collection,
        "exists": exists,
        "entities": count,
    }


def upsert_chunk(chunk_id: str, path: str, embedding: list[float]) -> None:
    if not milvus_enabled():
        return
    collection = _collection(dim=len(embedding))
    safe_id = chunk_id.replace("\\", "\\\\").replace('"', '\\"')
    collection.delete(expr=f'id == "{safe_id}"')
    collection.insert([[chunk_id], [path], [_normalize(embedding)]])
    collection.flush()


def delete_by_path(path: str) -> None:
    if not milvus_enabled():
        return
    from pymilvus import connections, utility

    connections.connect(alias="default", uri=settings.milvus_uri)
    if not utility.has_collection(settings.milvus_collection):
        return
    collection = _collection()
    safe_path = path.replace("\\", "\\\\").replace('"', '\\"')
    collection.delete(expr=f'path == "{safe_path}"')
    collection.flush()


def search_vectors(query_embedding: list[float], limit: int) -> list[dict[str, Any]]:
    if not milvus_enabled():
        return []
    collection = _collection(dim=len(query_embedding))
    results = collection.search(
        data=[_normalize(query_embedding)],
        anns_field="embedding",
        param={"metric_type": "IP", "params": {"ef": 64}},
        limit=limit,
        output_fields=["path"],
    )
    rows: list[dict[str, Any]] = []
    for hit in results[0]:
        rows.append({"id": str(hit.id), "vector_score": float(hit.score)})
    return rows
