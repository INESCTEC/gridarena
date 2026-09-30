"""HTTP connector: fetches data from external REST APIs with configurable auth."""

import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

from gridarena.digital_twin.schemas import SourceConfig

logger = logging.getLogger(__name__)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB


def _resolve_secret(secret_ref: Optional[str]) -> Optional[str]:
    """Resolve a secret reference to its value from environment variables."""
    if not secret_ref:
        return None
    value = os.environ.get(secret_ref)
    if value is None:
        logger.warning("Secret ref '%s' not found in environment variables.", secret_ref)
    return value


def _build_auth_headers(config: SourceConfig) -> Dict[str, str]:
    """Build authentication headers based on the source config."""
    headers = {}
    if config.auth_type == "none":
        return headers

    secret = _resolve_secret(config.secret_ref)
    if secret is None:
        logger.error("Auth type '%s' requires secret_ref but secret is not set.", config.auth_type)
        return headers

    if config.auth_type == "bearer":
        header_name = config.secret_header or "Authorization"
        headers[header_name] = f"Bearer {secret}"

    elif config.auth_type == "token":
        header_name = config.secret_header or "Authorization"
        headers[header_name] = f"Token {secret}"

    elif config.auth_type == "api_key":
        header_name = config.secret_header or "X-Api-Key"
        headers[header_name] = secret

    elif config.auth_type == "basic":
        header_name = config.secret_header or "Authorization"
        encoded = base64.b64encode(secret.encode()).decode()
        headers[header_name] = f"Basic {encoded}"

    return headers


async def fetch_source(config: SourceConfig) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str], Optional[int]]:
    """Fetch data from the configured external REST API.

    Returns:
        (success, payload_dict_or_none, error_message_or_none, http_status_code_or_none)
    """
    auth_headers = _build_auth_headers(config)
    all_headers = {**config.headers, **auth_headers}

    timeout = httpx.Timeout(config.timeout_seconds, connect=10.0)
    last_error = None
    status_code = None

    for attempt in range(max(config.retry_count, 1)):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                if config.method == "GET":
                    response = await client.get(
                        config.url,
                        headers=all_headers,
                        params=config.query_params or None,
                    )
                else:
                    response = await client.post(
                        config.url,
                        headers=all_headers,
                        params=config.query_params or None,
                        json=config.body_template,
                    )

            status_code = response.status_code

            if response.status_code == 401:
                return False, None, "Authentication failed (401). Check your credentials.", status_code
            if response.status_code == 403:
                return False, None, "Access forbidden (403). Check your permissions.", status_code

            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                continue

            if len(response.content) > MAX_RESPONSE_SIZE:
                return False, None, f"Response too large ({len(response.content)} bytes, max {MAX_RESPONSE_SIZE}).", status_code

            try:
                data = response.json()
            except Exception:
                return False, None, "Response is not valid JSON.", status_code

            if not isinstance(data, dict):
                return False, None, "Response JSON root must be an object.", status_code

            return True, data, None, status_code

        except httpx.TimeoutException:
            last_error = f"Request timed out after {config.timeout_seconds}s (attempt {attempt + 1})."
        except httpx.ConnectError as e:
            last_error = f"Connection error: {e} (attempt {attempt + 1})."
        except Exception as e:
            last_error = f"Unexpected error: {e} (attempt {attempt + 1})."

    return False, None, last_error or "All retry attempts failed.", status_code
