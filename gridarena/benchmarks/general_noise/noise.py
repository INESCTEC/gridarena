"""
Shared measurement corruption / noise insertion utilities.

Used across multiple benchmarks (phase detection, topology discovery, state estimation, etc.)
to apply consistent difficulty-based perturbations to measurement-like records.

Design goals:
- Same profiles everywhere (unless overridden)
- Same corruption logic everywhere
- Minimal changes to existing routers/helpers: keep old helper function names by wrapping.
"""

from __future__ import annotations

import math
import os
import random
from typing import Any, Dict, Literal, Optional

Difficulty = Literal["clean", "easy", "medium", "hard"]

# Default platform profiles (RELATIVE noise + rare outliers)
DEFAULT_PROFILES: Dict[str, Dict[str, float]] = {
    "clean":  {"pq_rel_sigma": 0.0,  "v_mag_rel_sigma": 0.0,   "v_ang_rel_sigma": 0.0,  "outlier_prob": 0.0,   "outlier_scale": 0.0},
    "easy":   {"pq_rel_sigma": 0.01, "v_mag_rel_sigma": 0.002, "v_ang_rel_sigma": 0.02, "outlier_prob": 0.002, "outlier_scale": 10.0},
    "medium": {"pq_rel_sigma": 0.03, "v_mag_rel_sigma": 0.005, "v_ang_rel_sigma": 0.06, "outlier_prob": 0.008, "outlier_scale": 12.0},
    "hard":   {"pq_rel_sigma": 0.07, "v_mag_rel_sigma": 0.010, "v_ang_rel_sigma": 0.15, "outlier_prob": 0.020, "outlier_scale": 15.0},
}

_ANGLE_UNIT = os.getenv("LVGPLAY_ANGLE_UNIT", "deg").strip().lower()  # "deg" or "rad"


def get_profile(
    difficulty: Difficulty,
    *,
    noise_scale: Optional[float] = None,
    outlier_prob: Optional[float] = None,
    outlier_scale: Optional[float] = None,
    profiles: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    Returns a numeric profile used by corrupt_measurement_record().

    - noise_scale multiplies all sigmas (keeps proportions).
    - outlier_prob overrides probability of outlier events.
    - outlier_scale overrides how large outliers are vs base sigma.
    - profiles allows swapping DEFAULT_PROFILES if a benchmark wants different baselines.
    """
    base = profiles if profiles is not None else DEFAULT_PROFILES

    if difficulty not in base:
        raise ValueError(f"Unsupported difficulty: {difficulty}")

    prof = dict(base[difficulty])

    if noise_scale is not None:
        s = float(noise_scale)
        prof["pq_rel_sigma"] *= s
        prof["v_mag_rel_sigma"] *= s
        prof["v_ang_rel_sigma"] *= s

    if outlier_prob is not None:
        prof["outlier_prob"] = float(outlier_prob)

    if outlier_scale is not None:
        prof["outlier_scale"] = float(outlier_scale)

    return prof


def get_series_rng(rngs: Dict[tuple, random.Random], series_key: tuple) -> random.Random:
    """
    Returns a per-series RNG object stored in `rngs`.

    This matches your current behaviour:
    - stable within a single endpoint call (same RNG reused per series_key)
    - NOT deterministic across calls (no explicit seed)
    """
    if series_key not in rngs:
        rngs[series_key] = random.Random()
    return rngs[series_key]


def _wrap_angle(x: float, *, angle_unit: Optional[str] = None) -> float:
    unit = (angle_unit or _ANGLE_UNIT).strip().lower()
    if unit == "rad":
        return ((x + math.pi) % (2.0 * math.pi)) - math.pi
    return ((x + 180.0) % 360.0) - 180.0


def _gauss(rng: random.Random, sigma: float) -> float:
    if sigma <= 0.0:
        return 0.0
    return rng.gauss(0.0, sigma)


def _maybe_outlier(
    rng: random.Random,
    base_sigma: float,
    outlier_prob: float,
    outlier_scale: float,
) -> float:
    """
    Additional error term representing an outlier spike.
    Outlier magnitude is Gaussian with sigma = outlier_scale * base_sigma.
    """
    if base_sigma <= 0.0 or outlier_prob <= 0.0 or outlier_scale <= 0.0:
        return 0.0
    if rng.random() < outlier_prob:
        return _gauss(rng, outlier_scale * base_sigma)
    return 0.0


def corrupt_measurement_record(
    record: Dict[str, Any],
    rng: random.Random,
    profile: Dict[str, float],
    *,
    angle_unit: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Applies Gaussian noise + occasional outliers to numeric measurement fields.

    Touches (if present):
      - power_active
      - power_reactive
      - voltage_magnitude
      - voltage_angle

    Leaves everything else unchanged (e.g., datetime, phase labels, ids, etc.)

    Noise is RELATIVE to magnitude:
      - power_*: sigma ~ pq_rel_sigma * max(|x|, pq_floor)
      - voltage_magnitude: sigma ~ v_mag_rel_sigma * max(|x|, v_mag_floor)
      - voltage_angle: sigma ~ v_ang_rel_sigma * max(|x|, v_ang_floor) then wrapped

    Floors avoid sigma=0 when values are near 0.
    """
    pq_rel_sigma = float(profile.get("pq_rel_sigma", 0.0))
    v_mag_rel_sigma = float(profile.get("v_mag_rel_sigma", 0.0))
    v_ang_rel_sigma = float(profile.get("v_ang_rel_sigma", 0.0))
    outlier_prob = float(profile.get("outlier_prob", 0.0))
    outlier_scale = float(profile.get("outlier_scale", 0.0))

    out = dict(record)

    pq_floor = 1e-6
    v_mag_floor = 1e-6

    # Angle often near 0; keep a meaningful floor.
    # Works as a stabiliser in both deg and rad (not “unit-perfect”, but consistent).
    v_ang_floor = 1.0

    if "power_active" in out and out["power_active"] is not None:
        x = float(out["power_active"])
        base_sigma = pq_rel_sigma * max(abs(x), pq_floor)
        out["power_active"] = x + _gauss(rng, base_sigma) + _maybe_outlier(rng, base_sigma, outlier_prob, outlier_scale)

    if "power_reactive" in out and out["power_reactive"] is not None:
        x = float(out["power_reactive"])
        base_sigma = pq_rel_sigma * max(abs(x), pq_floor)
        out["power_reactive"] = x + _gauss(rng, base_sigma) + _maybe_outlier(rng, base_sigma, outlier_prob, outlier_scale)

    if "voltage_magnitude" in out and out["voltage_magnitude"] is not None:
        x = float(out["voltage_magnitude"])
        base_sigma = v_mag_rel_sigma * max(abs(x), v_mag_floor)
        v = x + _gauss(rng, base_sigma) + _maybe_outlier(rng, base_sigma, outlier_prob, outlier_scale)
        out["voltage_magnitude"] = max(0.0, v)

    if "voltage_angle" in out and out["voltage_angle"] is not None:
        x = float(out["voltage_angle"])
        base_sigma = v_ang_rel_sigma * max(abs(x), v_ang_floor)
        a = x + _gauss(rng, base_sigma) + _maybe_outlier(rng, base_sigma, outlier_prob, outlier_scale)
        out["voltage_angle"] = _wrap_angle(a, angle_unit=angle_unit)

    return out