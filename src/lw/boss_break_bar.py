"""[lw] Read the boss break (倾陷) bar below the boss health bar.

The bar is a flat light-gray fill on a dark track. While the boss is not broken the
fill only shrinks under attacks; a break drops it to almost zero at once, after which
it refills from zero. Combat effects can briefly cover parts of the bar, so the fill
end tolerates short gaps and ignores isolated bright sparks on the empty track.
"""

from __future__ import annotations

import numpy as np

# Inner rows/columns of the bar, measured from a 16:9 capture.
BREAK_BAR_BOX = (0.3490, 0.0765, 0.6365, 0.0785)
_FILL_MIN_CHANNEL = 190
_FILL_MAX_SPREAD = 30
_FILLED_ROW_RATIO = 0.6
_FILL_DENSITY = 0.8
_FILL_END_WINDOW = 0.03


def break_bar_ratio(frame) -> float | None:
    """Return the remaining break-bar ratio in [0, 1], or None for an unusable frame."""

    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] < 3:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = BREAK_BAR_BOX
    left, right = round(width * x1), round(width * x2)
    top, bottom = round(height * y1), round(height * y2) + 1
    crop = frame[top:bottom, left:right, :3]
    if crop.size == 0:
        return None

    crop = crop.astype(np.int16)
    low = crop.min(axis=2)
    spread = crop.max(axis=2) - low
    fill_pixels = (low >= _FILL_MIN_CHANNEL) & (spread <= _FILL_MAX_SPREAD)
    filled_columns = fill_pixels.mean(axis=0) >= _FILLED_ROW_RATIO

    # The fill end is the last filled column closing a mostly-filled window: gaps
    # inside the fill do not matter, and a few bright sparks cannot form a window.
    columns = filled_columns.size
    window = max(3, round(columns * _FILL_END_WINDOW))
    counts = np.convolve(filled_columns.astype(np.int32), np.ones(window, dtype=np.int32))
    # counts[c] covers the window ending at column c.
    window_filled = counts[:columns] >= window * _FILL_DENSITY
    ends = np.nonzero(window_filled & filled_columns)[0]
    if ends.size == 0:
        return 0.0
    return float(ends[-1] + 1) / columns
