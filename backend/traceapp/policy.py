import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

class PolicyError(ValueError):
    pass

def public_ip(value):
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return public_ip(str(ip.ipv4_mapped))
    return ip.is_global and not ip.is_multicast and not ip.is_reserved and not ip.is_unspecified

def validate_url(url):
    if len(url) > 2048 or any(ord(c) < 33 for c in url) or '\\' in url:
        raise PolicyError('URL contains unsupported characters')
    try:
        u = urlsplit(url)
        port = u.port
        host = u.hostname
    except ValueError as e:
        raise PolicyError('Invalid URL') from e
    if u.scheme not in ('http', 'https') or not host or u.username is not None or u.password is not None:
        raise PolicyError('Use a public HTTP or HTTPS URL without credentials')
    if port not in (None, 80 if u.scheme == 'http' else 443):
        raise PolicyError('Only standard HTTP and HTTPS ports are supported')
    host = host.rstrip('.').lower().encode('idna').decode()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '%' in host:
        raise PolicyError('Private destinations are not permitted')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host:
            raise PolicyError('Use a public hostname')
    else:
        if not public_ip(host):
            raise PolicyError('Private destinations are not permitted')
    authority = '[' + host + ']' if ':' in host else host
    return urlunsplit((u.scheme, authority, u.path or '/', u.query, ''))

async def resolve_public(host, port):
    entries = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(e[4][0] for e in entries))
    if not addresses or any(not public_ip(ip) for ip in addresses):
        raise PolicyError('Destination resolves to a forbidden address')
    return addresses
