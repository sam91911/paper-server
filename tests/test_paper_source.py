import io
import socket
import unittest
from unittest.mock import Mock, patch

from paper_client import paper_source


class SourceResponse(io.BytesIO):
    def __init__(self, payload=b"", *, status=200, location=None):
        super().__init__(payload)
        self.status = status
        self.location = location

    def getheader(self, name):
        return self.location if name == "Location" else None


class PaperSourceTests(unittest.TestCase):
    def test_redirect_fetch_does_not_send_library_credentials(self):
        payload = b"%PDF-1.4\ntest payload"
        first = Mock()
        first.getresponse.return_value = SourceResponse(status=302, location="https://cdn.example.org/Paper%20A.pdf?v=2")
        final = Mock()
        final.getresponse.return_value = SourceResponse(payload)
        with patch.object(paper_source, "PublicHTTPSConnection", side_effect=[first, final]) as connect:
            self.assertEqual(paper_source.fetch_pdf("https://repository.example.org/a", 1024), ("Paper A.pdf", payload))
        self.assertEqual([call.args[0] for call in connect.call_args_list], ["repository.example.org", "cdn.example.org"])
        self.assertEqual(final.request.call_args.args, ("GET", "/Paper%20A.pdf?v=2"))
        self.assertEqual(set(final.request.call_args.kwargs["headers"]), {"Accept", "User-Agent"})

    def test_rejects_non_pdf_oversize_and_insecure_redirect(self):
        cases = (
            (SourceResponse(b"<html>Sign in</html>"), "did not return a PDF"),
            (SourceResponse(b"%PDF-" + b"x" * 2048), "exceeds"),
            (SourceResponse(status=302, location="http://repository.example.org/paper.pdf"), "public HTTPS"),
        )
        for response, message in cases:
            with self.subTest(message=message), patch.object(paper_source, "PublicHTTPSConnection") as connect:
                connect.return_value.getresponse.return_value = response
                with self.assertRaisesRegex(ValueError, message):
                    paper_source.fetch_pdf("https://repository.example.org/a", 1024)
                self.assertEqual(connect.call_count, 1)

    def test_refuses_private_dns_result_before_connecting(self):
        connection = paper_source.PublicHTTPSConnection("repository.example.org", 443)
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(socket, "getaddrinfo", return_value=addresses), patch.object(socket, "socket") as connect:
            with self.assertRaisesRegex(ValueError, "public IP"):
                connection.connect()
            connect.assert_not_called()
