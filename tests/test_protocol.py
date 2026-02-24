"""Tests for DAP protocol encoding/decoding."""

from __future__ import annotations

import pytest

from mcp_dap.dap.protocol import decode_message
from mcp_dap.dap.protocol import encode_message
from mcp_dap.dap.protocol import parse_content_length
from mcp_dap.exceptions import DAPProtocolError


class TestEncode:
    """Tests for message encoding."""

    def test_encode_simple_message(self) -> None:
        """Test encoding a simple message."""
        data = {"seq": 1, "type": "request", "command": "initialize"}
        encoded = encode_message(data)

        assert encoded.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in encoded
        assert b'"seq":1' in encoded

    def test_encode_message_with_arguments(self) -> None:
        """Test encoding a message with arguments."""
        data = {
            "seq": 2,
            "type": "request",
            "command": "setBreakpoints",
            "arguments": {"source": {"path": "/test.py"}, "breakpoints": [{"line": 10}]},
        }
        encoded = encode_message(data)

        header_end = encoded.index(b"\r\n\r\n")
        header = encoded[:header_end].decode("utf-8")
        content = encoded[header_end + 4 :]

        # Check content length matches
        length = int(header.split(": ")[1])
        assert len(content) == length


class TestParseContentLength:
    """Tests for Content-Length parsing."""

    def test_parse_valid_header(self) -> None:
        """Test parsing a valid Content-Length header."""
        header = b"Content-Length: 119"
        length = parse_content_length(header)
        assert length == 119

    def test_parse_case_insensitive(self) -> None:
        """Test that header parsing is case-insensitive."""
        header = b"content-length: 42"
        length = parse_content_length(header)
        assert length == 42

    def test_parse_missing_header(self) -> None:
        """Test that missing Content-Length raises error."""
        header = b"Content-Type: application/json"
        with pytest.raises(DAPProtocolError, match="Missing Content-Length"):
            parse_content_length(header)

    def test_parse_invalid_value(self) -> None:
        """Test that invalid Content-Length value raises error."""
        header = b"Content-Length: abc"
        with pytest.raises(DAPProtocolError, match="Invalid Content-Length"):
            parse_content_length(header)


class TestDecode:
    """Tests for message decoding."""

    def test_decode_valid_json(self) -> None:
        """Test decoding valid JSON content."""
        content = b'{"seq": 1, "type": "response"}'
        data = decode_message(content)
        assert data == {"seq": 1, "type": "response"}

    def test_decode_invalid_json(self) -> None:
        """Test that invalid JSON raises error."""
        content = b"not json"
        with pytest.raises(DAPProtocolError, match="Invalid JSON"):
            decode_message(content)

    def test_decode_non_object(self) -> None:
        """Test that non-object JSON raises error."""
        content = b"[1, 2, 3]"
        with pytest.raises(DAPProtocolError, match="must be an object"):
            decode_message(content)


class TestRoundTrip:
    """Tests for encode/decode round trip."""

    def test_roundtrip_simple(self) -> None:
        """Test encoding and decoding produces same data."""
        original = {"seq": 1, "type": "request", "command": "test"}
        encoded = encode_message(original)

        # Extract content after header
        header_end = encoded.index(b"\r\n\r\n")
        content = encoded[header_end + 4 :]

        decoded = decode_message(content)
        assert decoded == original

    def test_roundtrip_unicode(self) -> None:
        """Test round trip with unicode characters."""
        original = {"seq": 1, "type": "event", "event": "output", "body": {"output": "Hello "}}
        encoded = encode_message(original)

        header_end = encoded.index(b"\r\n\r\n")
        content = encoded[header_end + 4 :]

        decoded = decode_message(content)
        assert decoded == original
