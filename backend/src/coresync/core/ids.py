"""UUIDv7 generation (RFC 9562).

Time-ordered UUIDs: the first 48 bits are a Unix millisecond timestamp, so values
generated over time sort naturally and insert at the right-hand edge of a B-tree
instead of scattering across it like UUIDv4.

Implemented here rather than pulled from a dependency — it is 20 lines, and clients
(web and mobile) need a matching implementation, so having the canonical one in the
codebase is worth more than the import.

Layout:
    48 bits  unix_ts_ms
     4 bits  version (7)
    12 bits  rand_a      — sub-millisecond counter for monotonicity within a tick
     2 bits  variant (0b10)
    62 bits  rand_b
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

_lock = Lock()
_last_timestamp_ms = 0
_counter = 0


def uuid7() -> UUID:
    """Generate a time-ordered UUIDv7.

    Monotonic within a process: two calls in the same millisecond still sort in
    creation order, which matters because sets logged in rapid succession must keep
    their sequence.
    """
    global _last_timestamp_ms, _counter

    with _lock:
        timestamp_ms = time.time_ns() // 1_000_000
        if timestamp_ms == _last_timestamp_ms:
            _counter += 1
            if _counter > 0xFFF:  # 12-bit counter exhausted; wait for the next tick
                while timestamp_ms <= _last_timestamp_ms:
                    timestamp_ms = time.time_ns() // 1_000_000
                _counter = 0
        else:
            _last_timestamp_ms = timestamp_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x0FF  # random low start
        counter = _counter
        _last_timestamp_ms = timestamp_ms

    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value = (
        (timestamp_ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | (counter & 0xFFF) << 64
        | 0b10 << 62
        | rand_b
    )
    return UUID(int=value)


def uuid7_timestamp(value: UUID) -> datetime:
    """Extract the creation time embedded in a UUIDv7.

    Useful in support and debugging: any id in a log line reveals when it was made.
    """
    if value.version != 7:
        raise ValueError(f"not a UUIDv7: {value}")
    timestamp_ms = value.int >> 80
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
