"""Declarative field mapper: converts external API payloads into GridArena-compatible measurements."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from gridarena.digital_twin.schemas import FieldMapping, StreamedMeasurement, StreamedMeasurementBatch


import re

_INDEX_RE = re.compile(r"^(.+?)\[(-?\d+)\]$")
_BARE_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


def resolve_path(data: Any, path: str) -> Any:
    """Resolve a dot-separated path against a nested dict/list structure.

    Supports:
      - "field"               simple key
      - "data.measurements"   nested keys
      - "items[].value"       iterate over list, returning list of resolved sub-paths
      - "data[0].value"       index into list (0 = first / latest)
      - "data[-1].value"      negative index (last element)
    """
    if not path:
        return data

    parts = path.split(".")
    current = data

    for i, part in enumerate(parts):
        if current is None:
            return None

        if part.endswith("[]"):
            key = part[:-2]
            if key:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    return None
            if not isinstance(current, list):
                return None
            remaining = ".".join(parts[i + 1:])
            if remaining:
                return [resolve_path(item, remaining) for item in current]
            return current

        m = _INDEX_RE.match(part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
            if isinstance(current, list):
                try:
                    current = current[idx]
                except IndexError:
                    return None
            else:
                return None
            continue

        bm = _BARE_INDEX_RE.match(part)
        if bm:
            idx = int(bm.group(1))
            if isinstance(current, list):
                try:
                    current = current[idx]
                except IndexError:
                    return None
            else:
                return None
            continue

        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


def _parse_timestamp(value: Any) -> Optional[str]:
    """Parse a timestamp value into ISO 8601 string."""
    if value is None:
        return None
    s = str(value).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    try:
        ts = float(s)
        return datetime.utcfromtimestamp(ts).isoformat()
    except (ValueError, OSError):
        pass
    return s


def _to_float(value: Any, field_name: str) -> Tuple[Optional[float], Optional[str]]:
    """Convert a value to float, returning (value, error_message)."""
    if value is None:
        return None, f"Field '{field_name}' is missing"
    try:
        return float(value), None
    except (ValueError, TypeError):
        return None, f"Field '{field_name}': cannot convert {value!r} to float"


VALID_PHASES = {"R", "S", "T"}


def map_payload(
    source_data: Dict[str, Any],
    mapping: FieldMapping,
    grid_id: str,
) -> Tuple[Optional[StreamedMeasurementBatch], List[str], List[str]]:
    """Map an external source payload into a GridArena-compatible measurement batch.

    Returns:
        (batch_or_None, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    ts_raw = resolve_path(source_data, mapping.timestamp)
    if ts_raw is None:
        errors.append(f"Timestamp field '{mapping.timestamp}' not found in source payload.")
        return None, errors, warnings

    timestamp = _parse_timestamp(ts_raw)
    if timestamp is None:
        errors.append(f"Cannot parse timestamp value: {ts_raw!r}")
        return None, errors, warnings

    measurements_raw = resolve_path(source_data, mapping.measurements)
    if measurements_raw is None:
        errors.append(f"Measurements field '{mapping.measurements}' not found in source payload.")
        return None, errors, warnings
    if not isinstance(measurements_raw, list):
        errors.append(f"Measurements field '{mapping.measurements}' is not a list.")
        return None, errors, warnings
    if len(measurements_raw) == 0:
        errors.append("Measurements array is empty.")
        return None, errors, warnings

    measurements: List[StreamedMeasurement] = []
    seen = set()

    for idx, item in enumerate(measurements_raw):
        if not isinstance(item, dict):
            errors.append(f"Measurement [{idx}]: expected dict, got {type(item).__name__}.")
            continue

        node_id = resolve_path(item, mapping.node_id)
        if node_id is None:
            errors.append(f"Measurement [{idx}]: node_id field '{mapping.node_id}' not found.")
            continue
        node_id = str(node_id)

        phase = None
        if mapping.phase:
            phase_raw = resolve_path(item, mapping.phase)
            if phase_raw is not None:
                phase = str(phase_raw).upper()
                if phase not in VALID_PHASES:
                    errors.append(f"Measurement [{idx}]: invalid phase '{phase}' (expected R, S, or T).")
                    continue

        p_active, err = _to_float(resolve_path(item, mapping.active_power), f"[{idx}].active_power")
        if err:
            errors.append(f"Measurement {err}")
            continue

        p_reactive, err = _to_float(resolve_path(item, mapping.reactive_power), f"[{idx}].reactive_power")
        if err:
            errors.append(f"Measurement {err}")
            continue

        v_mag, err = _to_float(resolve_path(item, mapping.voltage_magnitude), f"[{idx}].voltage_magnitude")
        if err:
            errors.append(f"Measurement {err}")
            continue

        v_angle = 0.0
        if mapping.voltage_angle:
            v_angle_raw = resolve_path(item, mapping.voltage_angle)
            if v_angle_raw is not None:
                v_angle, err = _to_float(v_angle_raw, f"[{idx}].voltage_angle")
                if err:
                    warnings.append(f"Measurement {err}; defaulting to 0.0")
                    v_angle = 0.0

        if v_mag is not None and v_mag < 0:
            errors.append(f"Measurement [{idx}]: voltage_magnitude ({v_mag}) is negative.")
            continue

        dedup_key = (node_id, phase, timestamp)
        if dedup_key in seen:
            errors.append(f"Measurement [{idx}]: duplicate entry for node '{node_id}', phase '{phase}', timestamp '{timestamp}'.")
            continue
        seen.add(dedup_key)

        measurements.append(StreamedMeasurement(
            node_id=node_id,
            phase=phase,
            datetime=timestamp,
            power_active=p_active,
            power_reactive=p_reactive,
            voltage_magnitude=v_mag,
            voltage_angle=v_angle,
        ))

    if not measurements:
        errors.append("No valid measurements after mapping.")
        return None, errors, warnings

    batch = StreamedMeasurementBatch(
        grid_id=grid_id,
        timestamp=timestamp,
        measurements=measurements,
    )
    return batch, errors, warnings


def validate_against_grid(
    batch: StreamedMeasurementBatch,
    grid_node_ids: set,
) -> Tuple[List[str], List[str], List[str]]:
    """Validate a mapped batch against known grid nodes.

    Returns:
        (invalid_nodes, invalid_phases, warnings)
    """
    invalid_nodes = []
    invalid_phases = []
    warnings = []

    for m in batch.measurements:
        if m.node_id not in grid_node_ids:
            invalid_nodes.append(m.node_id)
        if m.phase is not None and m.phase not in VALID_PHASES:
            invalid_phases.append(m.phase)

    return invalid_nodes, invalid_phases, warnings
