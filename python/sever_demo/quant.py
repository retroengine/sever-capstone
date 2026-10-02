import numpy as np
import numpy.typing as npt

SCALE = 2**24            # §4.2: Q24 means "times 2^24"
BOUND = 2**24 + 16       # §4.2: largest |x̃| a row inside the §4.1 tolerance can produce


# §4.2: x̃ = round_half_to_even((f64)x * 2^24), stored as i32
def quantise(x: npt.ArrayLike) -> npt.NDArray[np.int32]:
    # float32 -> float64 is exact, and so is multiplying by a power of two (§4.2),
    # so np.rint below is the only rounding step.
    scaled = np.asarray(x, dtype=np.float64) * SCALE

    # Check before casting: NaN or inf cast to int32 gives a meaningless number, not an error.
    # §17: the message never contains the vector's values.
    if not np.isfinite(scaled).all():
        raise ValueError("quantise: non-finite component")

    # np.rint rounds ties to even (IEEE 754 default): 0.5 -> 0, 1.5 -> 2, 2.5 -> 2 (§4.2)
    rounded = np.rint(scaled)

    # §4.2 bound. Only reachable if a row skipped the §4.1 norm check; refuse rather than wrap.
    if np.abs(rounded).max(initial=0) > BOUND:
        raise ValueError("quantise: component beyond 2^24 + 16")

    return rounded.astype(np.int32)


# §4.3: x̂ = x̃ / 2^24, in float64 (exact)
def dequantise(q: npt.ArrayLike) -> npt.NDArray[np.float64]:
    return np.asarray(q, dtype=np.float64) / SCALE
