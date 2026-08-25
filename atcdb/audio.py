"""Audio helpers shared by the loader and the enrichment script."""
import hashlib
import io

import numpy as np
import soundfile as sf


def pcm_sha1(wav_bytes: bytes) -> tuple[str, int]:
    """sha1 of the decoded int16 samples (header-independent) and the sample rate."""
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="int16")
    return hashlib.sha1(np.ascontiguousarray(data).tobytes()).hexdigest(), int(sr)
