"""Shared guard for upload endpoints: reject oversized files up front,
before their content is read fully into memory for JSON parsing.
"""

from fastapi import HTTPException, UploadFile

DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


def ensure_upload_size_ok(file: UploadFile, max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> None:
    """Raise 413 if the upload exceeds max_bytes.

    Starlette already knows the spooled file's size by the time the route
    handler runs, so this doesn't require reading the file ourselves. Bulk
    loads that legitimately exceed this (e.g. the historical
    feeder-measurements import) go through a direct script against the
    database rather than this HTTP path, so this ceiling only guards
    against pathological/mistaken uploads.
    """
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file is too large ({file.size} bytes; max {max_bytes} bytes).",
        )
