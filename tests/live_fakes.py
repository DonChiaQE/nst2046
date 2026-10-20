"""Stand-ins shared by the live demo's tests (tests/test_live.py, tests/test_live_api.py)."""
import io
import time

import numpy as np
import soundfile as sf

from atcdb.engine import ClearTakeoff, ClearToLand


def wav(seconds, rate=16000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * rate), dtype=np.float32), rate, format="WAV")
    return buf.getvalue()


class Scripted:
    """A stand-in for the Claude parser: events chosen by the transmission's text; can be slow, fail, or record the
    context it was given."""

    def __init__(self, delay=0.0, fail_texts=(), fail_times=1):
        self.delay, self.fail = delay, {t: fail_times for t in fail_texts}
        self.contexts, self.calls = [], []

    def __call__(self, tx, ctx):
        self.calls.append(tx.text)
        self.contexts.append(ctx)
        time.sleep(self.delay)
        if self.fail.get(tx.text, 0) > 0:
            self.fail[tx.text] -= 1
            raise RuntimeError("Claude unavailable: no internet connection")
        if "cleared to land" in tx.text:
            rwy = "18L" if "one eight left" in tx.text else "31"
            return [ClearToLand(callsign=" ".join(tx.text.split()[:4]), runway=rwy, t=tx.start_s, text=tx.text)]
        if "cleared for takeoff" in tx.text:
            rwy = "18L" if "one eight left" in tx.text else "31"
            return [ClearTakeoff(callsign=" ".join(tx.text.split()[:4]), runway=rwy, t=tx.start_s, text=tx.text)]
        return []
