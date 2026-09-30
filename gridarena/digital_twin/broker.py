"""Redis Streams broker: publish and consume GridArena-compatible measurement messages."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def _get_redis():
    """Lazy-initialise the Redis client."""
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.Redis.from_url(
            _get_redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def topic_for_digital_twin(digital_twin_id: str) -> str:
    return f"gridarena.digital_twin.{digital_twin_id}.measurements"


def publish_measurement(digital_twin_id: str, payload: dict, topic: Optional[str] = None) -> str:
    """Publish a GridArena-compatible measurement batch to Redis Streams.

    Returns the stream message ID.
    """
    r = _get_redis()
    stream_key = topic or topic_for_digital_twin(digital_twin_id)
    message_id = r.xadd(stream_key, {"payload": json.dumps(payload)}, maxlen=1000)
    return message_id


def consume_latest(digital_twin_id: str, topic: Optional[str] = None) -> Optional[dict]:
    """Consume the latest message from the digital twin's measurement stream.

    Returns the parsed payload dict or None if no messages.
    """
    r = _get_redis()
    stream_key = topic or topic_for_digital_twin(digital_twin_id)

    messages = r.xrevrange(stream_key, count=1)
    if not messages:
        return None

    _msg_id, fields = messages[0]
    raw = fields.get("payload")
    if raw is None:
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse broker message payload for %s", digital_twin_id)
        return None


def consume_since(digital_twin_id: str, last_id: str = "0-0",
                  count: int = 100, topic: Optional[str] = None) -> List[Dict[str, Any]]:
    """Consume messages after last_id from the stream.

    Returns list of {"id": msg_id, "payload": dict}.
    """
    r = _get_redis()
    stream_key = topic or topic_for_digital_twin(digital_twin_id)

    messages = r.xrange(stream_key, min=f"({last_id}", count=count)
    results = []
    for msg_id, fields in messages:
        raw = fields.get("payload")
        if raw:
            try:
                results.append({"id": msg_id, "payload": json.loads(raw)})
            except (json.JSONDecodeError, TypeError):
                continue
    return results


def is_available() -> bool:
    """Test Redis connectivity. Returns True if reachable."""
    global _redis_client
    try:
        r = _get_redis()
        r.ping()
        return True
    except Exception:
        _redis_client = None
        return False


check_broker_connection = is_available


def delete_stream(digital_twin_id: str, topic: Optional[str] = None):
    """Delete the stream for a digital twin (cleanup)."""
    try:
        r = _get_redis()
        stream_key = topic or topic_for_digital_twin(digital_twin_id)
        r.delete(stream_key)
    except Exception as e:
        logger.warning("Failed to delete stream for %s: %s", digital_twin_id, e)


def shutdown():
    """Close the Redis connection."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass
        _redis_client = None
