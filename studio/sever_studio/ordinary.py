"""The same notes app on an ordinary vector store: Chroma, as a company would set it up.

``chromadb.PersistentClient`` with its default storage settings (only its usage telemetry is turned
off, so the demo sends nothing anywhere). The notes go in with the same IDs, text and vectors as in
SEVER-DB; ``delete`` is Chroma's own. Afterwards its folder is searched byte by byte exactly as
SEVER-DB's files are (``tools.count_hits``). Whatever is found is shown as found, even if it is
nothing: Studio measures it, it never assumes it.
"""

import gc
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from . import tools

Vector = npt.NDArray[np.float32]
COLLECTION = "acme-notes"


@dataclass
class Scan:
    files: int
    hits: dict[str, tuple[int, int]]


class Ordinary:
    def __init__(self, folder: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            str(folder), settings=Settings(anonymized_telemetry=False)
        )
        self.col = self.client.get_or_create_collection(COLLECTION)

    def store(self, name: str, ids: list[str], texts: list[str], vectors: list[Vector]) -> None:
        self.col.add(
            ids=ids,
            documents=texts,
            embeddings=np.asarray(vectors, np.float32),
            metadatas=[{"account": name} for _ in ids],
        )

    def query(self, vector: Vector, k: int = 5) -> list[str]:
        n = self.col.count()
        if n == 0:
            return []
        out = self.col.query(query_embeddings=np.asarray([vector], np.float32), n_results=min(k, n))
        return list(out["ids"][0])

    def read(self, ids: list[str]) -> list[str]:
        """The IDs Chroma's ``get`` still returns, with their documents."""
        return list(self.col.get(ids=ids)["ids"])

    def delete(self, ids: list[str]) -> None:
        self.col.delete(ids=ids)

    def scan(self, ids: list[str], texts: list[str], vectors: list[Vector]) -> Scan:
        gc.collect()  # let Chroma finish writing what it holds in memory
        files = tools.files_under([self.folder])
        return Scan(len(files), tools.count_hits(files, tools.needles_of(ids, texts, vectors)))
