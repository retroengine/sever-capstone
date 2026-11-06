"""§4.2 written out again by Studio, for the Groups made screen only (labelled there as Studio's).

x̃ = round(x · 2²⁴), ties to even, as whole numbers; x̂ = x̃ / 2²⁴. The database does its own
arithmetic; Studio shows this beside it and never feeds it back.
"""

import numpy as np
import numpy.typing as npt

SCALE = 2.0**24


def quantise(x: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """§4.2: each component times 2²⁴ in float64 (exact for float32 input), rounded half to even."""
    return np.rint(np.asarray(x, np.float64) * SCALE).astype(np.int64)


def dequantise(q: npt.ArrayLike) -> npt.NDArray[np.float64]:
    return np.asarray(q, np.float64) / SCALE
