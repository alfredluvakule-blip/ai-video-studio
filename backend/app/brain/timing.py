"""Durations that add up exactly to the length the user asked for."""
from __future__ import annotations

import math

WORDS_PER_SECOND = {"en": 2.5, "sw": 2.2}
LENGTH_PRESETS = [30, 60, 180, 300, 600, 900, 1800, 3600]


def words_per_second(language: str) -> float:
    return WORDS_PER_SECOND.get(language, 2.4)


def word_budget(seconds: float, language: str) -> int:
    """Spoken words that fit in a scene, leaving a little breathing room."""
    return max(3, int(seconds * words_per_second(language) * 0.85))


def chapter_range(target_seconds: int) -> tuple[int, int]:
    """How many chapters a video of this length should have."""
    if target_seconds <= 90:
        return 1, 2
    if target_seconds <= 300:
        return 3, 5
    if target_seconds <= 900:
        return 4, 8
    return max(5, target_seconds // 600), min(20, max(8, target_seconds // 180))


def scene_count(target_seconds: int, scene_seconds: float) -> int:
    return max(1, round(target_seconds / scene_seconds))


def split_scenes(n_scenes: int, weights: list[float]) -> list[int]:
    """Share n_scenes between chapters by weight (largest remainder), at least one each."""
    k = len(weights)
    if k == 0:
        return []
    if n_scenes < k:  # fewer scenes than chapters: the first chapters get one each
        return [1 if i < n_scenes else 0 for i in range(k)]
    w = [max(0.01, float(x or 0)) for x in weights]
    total = sum(w)
    spare = n_scenes - k
    raw = [spare * x / total for x in w]
    counts = [1 + math.floor(r) for r in raw]
    left = n_scenes - sum(counts)
    order = sorted(range(k), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)
    for i in order[:left]:
        counts[i] += 1
    return counts


def scene_durations(target_seconds: float, n_scenes: int) -> list[float]:
    """n durations (0.1 s steps) whose sum is exactly target_seconds."""
    if n_scenes <= 0:
        return []
    tenths = round(target_seconds * 10)
    base, extra = divmod(tenths, n_scenes)
    return [(base + (1 if i < extra else 0)) / 10 for i in range(n_scenes)]


def rebalance(scenes: list[dict], target_seconds: float) -> None:
    """Scale the scenes' durations (in place) so they add up to the target, keeping their proportions."""
    if not scenes:
        return
    cur = [max(0.5, float(s.get("duration") or 0)) for s in scenes]
    total = sum(cur)
    tenths = round(target_seconds * 10)
    scaled = [max(10, math.floor(c / total * tenths)) for c in cur]
    diff = tenths - sum(scaled)
    i = 0
    while diff != 0 and i < 100000:
        j = i % len(scaled)
        step = 1 if diff > 0 else -1
        if scaled[j] + step >= 10:
            scaled[j] += step
            diff -= step
        i += 1
    for s, t in zip(scenes, scaled):
        s["duration"] = t / 10


def total(scenes: list[dict]) -> float:
    return round(sum(float(s.get("duration") or 0) for s in scenes), 1)
