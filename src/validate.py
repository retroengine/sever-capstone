import numpy as np, pandas as pd
from sentence_transformers import SentenceTransformer

emb = np.load("embeddings.npy")              # (3452, 384)
df  = pd.read_parquet("data.parquet")        # should have 3452 rows
assert len(df) == len(emb), "row mismatch: the files are not aligned"

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
q = model.encode("your question here", normalize_embeddings=True)

scores = emb @ q
top = np.argsort(-scores)[:5]
print(df.iloc[top].assign(score=scores[top]))