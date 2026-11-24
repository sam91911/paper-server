"""Download an unauthenticated PDF from a public HTTPS source."""

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import unquote, urljoin, urlsplit


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port, timeout=30, context=self.tls_context)

    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        for _, _, _, _, address in addresses:
            ip = ipaddress.ip_address(address[0])
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise ValueError("The PDF source must resolve to a public IP address.")
        for family, kind, protocol, _, address in addresses:
            sock = socket.socket(family, kind, protocol)
            sock.settimeout(self.timeout)
            try:
                # Connect to the checked address and verify TLS for the original hostname.
                sock.connect(address)
                self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
                return
            except ssl.SSLError:
                sock.close()
                raise
            except OSError:
                sock.close()
        raise OSError("Could not connect to the public PDF source.")


def validate_source(url):
    source = urlsplit(url)
    if (source.scheme != "https" or not source.hostname or source.username is not None
            or source.fragment or source.port == 0 or not url.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
        raise ValueError("Use a public HTTPS PDF URL without credentials or a fragment.")
    return source


def source_filename(path):
    name = unquote(path.rsplit("/", 1)[-1])
    name = re.sub(r"[\\/\x00-\x1f\x7f]", "_", name).strip(" .")
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    return (stem.encode()[:236].decode("utf-8", errors="ignore") or "paper") + ".pdf"


def fetch_pdf(url, limit):
    for _ in range(6):
        source = validate_source(url)
        connection = PublicHTTPSConnection(source.hostname, source.port or 443)
        try:
            target = source.path or "/"
            if source.query:
                target += "?" + source.query
            connection.request("GET", target, headers={"Accept": "application/pdf", "User-Agent": "PaperLibrary"})
            with connection.getresponse() as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("The PDF source returned a redirect without a location.")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError(f"The PDF source returned HTTP {response.status}.")
                prefix = response.read(min(limit + 1, 1024))
                if len(prefix) > limit:
                    raise ValueError("The source PDF exceeds the 50 MiB import limit.")
                if b"%PDF-" not in prefix:
                    raise ValueError("The URL did not return a PDF. Use a direct PDF link.")
                payload = prefix + response.read(limit - len(prefix) + 1)
                if len(payload) > limit:
                    raise ValueError("The source PDF exceeds the 50 MiB import limit.")
                return source_filename(source.path), payload
        except http.client.HTTPException as error:
            raise ValueError("The PDF source returned an incomplete or invalid HTTP response.") from error
        finally:
            connection.close()
    raise ValueError("The PDF source returned too many redirects.")
