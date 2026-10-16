"""Public fetch refuses rebinding, credentials, private redirects and oversized responses."""

import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.agent.dsh.web import PageText, fetch_page, public_address
from core.safety.guardrails import SafetyGuardrails


def dns(address: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


class TestDshWeb:
    def test_rebinding_and_credentials_rejected(self, tmp_path: Path, monkeypatch) -> None:
        guard = SafetyGuardrails(tmp_path)
        monkeypatch.setattr(guard, "validate_web_url", lambda url: None)
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: dns("127.0.0.1"))
        with pytest.raises(ValueError, match="非公网"):
            public_address("https://example.com", guard)
        with pytest.raises(ValueError, match="凭据"):
            public_address("https://user:password@example.com", guard)

    def test_pins_address_and_validates_redirect(self, tmp_path: Path, monkeypatch) -> None:
        guard = SafetyGuardrails(tmp_path)
        monkeypatch.setattr(
            guard, "validate_web_url", lambda url: "blocked" if "localhost" in url else None
        )
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: dns("93.184.216.34"))
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = "http://localhost/private"
        create = Mock()
        monkeypatch.setattr(socket, "create_connection", create)
        monkeypatch.setattr(
            "core.agent.dsh.web.http.client.HTTPConnection", lambda *a, **kw: connection
        )
        with pytest.raises(ValueError, match="安全检查"):
            fetch_page("http://example.com", guard, 1000)
        create.assert_called_once_with(("93.184.216.34", 80), timeout=10)
        connection.close.assert_called_once()

    def test_bounded_plaintext_and_hidden_html(self, tmp_path: Path, monkeypatch) -> None:
        guard = SafetyGuardrails(tmp_path)
        monkeypatch.setattr(
            "core.agent.dsh.web.public_address", lambda *a: ("example.com", 80, "93.184.216.34")
        )
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda name: {"Content-Type": "text/html"}.get(name)
        response.read.return_value = (
            b'<p>visible</p><script>hidden</script><a href="https://example.org">source</a>'
        )
        monkeypatch.setattr(socket, "create_connection", Mock())
        monkeypatch.setattr(
            "core.agent.dsh.web.http.client.HTTPConnection", lambda *a, **kw: connection
        )
        result = fetch_page("http://example.com", guard, 200)
        assert "visible" in result and "hidden" not in result and "https://example.org" in result
        assert len(result) <= 200
        response.read.return_value = b"x" * 512001
        with pytest.raises(ValueError, match="上限"):
            fetch_page("http://example.com", guard, 200)

    def test_search_rss_and_entity_rejection(self, tmp_path: Path, monkeypatch) -> None:
        guard = SafetyGuardrails(tmp_path)
        monkeypatch.setattr(
            "core.agent.dsh.web.public_address", lambda *a: ("example.com", 80, "93.184.216.34")
        )
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda name: {"Content-Type": "text/xml"}.get(name)
        response.read.return_value = b"<rss><channel><item><title>Result</title><link>https://example.org</link><description>Snippet</description></item></channel></rss>"
        monkeypatch.setattr(socket, "create_connection", Mock())
        monkeypatch.setattr(
            "core.agent.dsh.web.http.client.HTTPConnection", lambda *a, **kw: connection
        )
        assert "Result\nhttps://example.org\nSnippet" in fetch_page(
            "http://example.com", guard, 1000
        )
        for invalid in (b'<!DOCTYPE rss [<!ENTITY a "bad">]><rss/>', b"<broken", b"<rss/>"):
            response.read.return_value = invalid
            with pytest.raises(ValueError):
                fetch_page("http://example.com", guard, 1000)

    def test_markup_never_executes(self) -> None:
        parser = PageText()
        parser.feed('<style>secret</style><p>safe</p><a href="javascript:alert(1)">link</a>')
        assert "secret" not in "".join(parser.text)
        assert "javascript" not in "".join(parser.text)
