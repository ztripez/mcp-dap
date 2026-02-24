"""DAP message framing protocol.

DAP uses HTTP-style headers for message framing:
    Content-Length: <length>\r\n
    \r\n
    <JSON payload>
"""

from __future__ import annotations

import json
from typing import Any

from mcp_dap.exceptions import DAPProtocolError

HEADER_SEPARATOR = b"\r\n\r\n"
CONTENT_LENGTH_HEADER = b"Content-Length: "


def encode_message(data: dict[str, Any]) -> bytes:
    """Encode a DAP message with Content-Length header.

    Args:
        data: The message data to encode.

    Returns:
        The encoded message bytes.
    """
    content = json.dumps(data, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(content)}\r\n\r\n".encode()
    return header + content


def parse_content_length(header_data: bytes) -> int:
    """Parse Content-Length from header data.

    Args:
        header_data: The header bytes (without trailing CRLF CRLF).

    Returns:
        The content length value.

    Raises:
        DAPProtocolError: If Content-Length header is missing or invalid.
    """
    try:
        header_str = header_data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DAPProtocolError("Invalid header encoding") from e

    for line in header_str.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError as e:
                raise DAPProtocolError(f"Invalid Content-Length value: {line}") from e

    raise DAPProtocolError("Missing Content-Length header")


def decode_message(content: bytes) -> dict[str, Any]:
    """Decode a DAP message body.

    Args:
        content: The JSON content bytes.

    Returns:
        The decoded message dictionary.

    Raises:
        DAPProtocolError: If the content is not valid JSON.
    """
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DAPProtocolError(f"Invalid JSON in DAP message: {e}") from e

    if not isinstance(data, dict):
        raise DAPProtocolError(f"DAP message must be an object, got {type(data).__name__}")

    return data
