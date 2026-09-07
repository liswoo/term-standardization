from functools import lru_cache
from threading import RLock
import numpy as np
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from .config import EMBEDDING_MODEL, ROOT

_lock = RLock()

@lru_cache(maxsize=1)
def model():
    if EMBEDDING_MODEL == "intfloat/multilingual-e5-small":
        TextEmbedding.add_custom_model(model=EMBEDDING_MODEL, pooling=PoolingType.MEAN,
            normalization=True, sources=ModelSource(hf=EMBEDDING_MODEL), dim=384,
            model_file="onnx/model.onnx")
    return TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=str(ROOT / ".cache"), threads=2)

def embed(text: str, query=False) -> np.ndarray:
    if len(text) > 6000:
        raise ValueError("Embedding input too long")
    with _lock:
        # Custom-model generic embed does not add E5 prefixes automatically.
        iterator = model().embed([("query: " if query else "passage: ") + text])
        vector = np.asarray(next(iter(iterator)), dtype=np.float32)
    if vector.shape != (384,) or not np.isfinite(vector).all():
        raise ValueError("Invalid embedding; schema expects multilingual-e5-small dimension 384")
    return vector
