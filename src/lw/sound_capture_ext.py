# [lw] Producer-side audio observation before the RU latest-only queue drops backlog.

import threading
import time
from collections.abc import Callable

import numpy as np
from ok import Logger


logger = Logger.get_logger(__name__)

AudioChunkObserver = Callable[[np.ndarray, float], None]


class AudioCaptureExtMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lw_chunk_observer_lock = threading.Lock()
        self._lw_chunk_observer: AudioChunkObserver | None = None

    def lw_set_chunk_observer(self, observer: AudioChunkObserver | None) -> None:
        with self._lw_chunk_observer_lock:
            self._lw_chunk_observer = observer

    def lw_observe_captured_chunk(self, chunk: np.ndarray) -> None:
        with self._lw_chunk_observer_lock:
            observer = self._lw_chunk_observer
        if observer is None:
            return
        try:
            observer(chunk, time.perf_counter())
        except Exception as exc:
            logger.warning(f"Captured audio observer failed: {exc}")
