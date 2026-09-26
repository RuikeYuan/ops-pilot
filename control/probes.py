"""Public endpoint probes: validate every IP and pin the socket to the result."""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit


def parse_url(url):
    try:
        p = urlsplit(url)
        if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or p.fragment:
            raise ValueError('Use an HTTP(S) URL without credentials or fragments')
        port = p.port or (443 if p.scheme == 'https' else 80)
        if port not in (80, 443):
            raise ValueError('Only ports 80 and 443 are supported')
        if any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError('URL cannot contain whitespace')
        return p, port
    except (ValueError, AttributeError) as exc:
        raise ValueError('Use a valid public HTTP(S) URL on port 80 or 443') from exc


def public_address(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private, loopback and reserved addresses are blocked; use a heartbeat for private services')
    return addresses[0][4][0]


def probe(url, expected=200):
    start = time.monotonic()
    connection = None
    try:
        p, port = parse_url(url)
        address = public_address(p.hostname, port)
        connection = http.client.HTTPConnection(p.hostname, port, timeout=8)
        sock = socket.create_connection((address, port), timeout=8)
        if p.scheme == 'https':
            try:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            except Exception:
                sock.close()
                raise
        connection.sock = sock
        path = (p.path or '/') + ('?' + p.query if p.query else '')
        connection.request('GET', path, headers={'User-Agent': 'OpsPilot/0.2', 'Connection': 'close'})
        response = connection.getresponse()
        passed = response.status == expected
        detail = f'HTTP {response.status}; expected {expected}. TLS verified.' if p.scheme == 'https' else f'HTTP {response.status}; expected {expected}.'
        if 300 <= response.status < 400:
            detail += ' Redirects are not followed; configure the final URL.'
        return passed, round((time.monotonic() - start) * 1000), detail
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return False, round((time.monotonic() - start) * 1000), str(exc)[:300]
    finally:
        if connection:
            connection.close()
