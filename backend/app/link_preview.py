"""Vista previa de los enlaces de los mensajes (título, descripción, imagen y sitio), como en WhatsApp.

El servidor pide la página con cuidado, porque la dirección la escribe cualquiera (un cliente, un compañero):
- solo http y https, en los puertos de siempre (80 y 443) y sin usuario ni contraseña en la dirección;
- nunca a direcciones internas (la red de la oficina, este mismo equipo, la nube…), tampoco tras una redirección;
- como mucho 3 redirecciones, 5 segundos y 512 KB, y solo si es HTML.
La imagen se guarda como miniatura en base64 (data:…) de hasta 150 KB: el navegador la muestra sin pedir nada fuera.
Todo queda en link_previews para no repetir la petición (lo que falla se vuelve a intentar pasado un día)."""
import base64
import ipaddress
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser

from .company import sniff_image
from .config import config
from .db import get_conn
from .repositories import link_previews as repo

log = logging.getLogger(__name__)

ENABLED = not config.integrations.link_previews_disabled  # las pruebas lo apagan: nunca salen a internet
MAX_PAGE = 512 * 1024
MAX_IMAGE = 150 * 1024
TIMEOUT = 5
RETRY_AFTER = timedelta(days=1)
USER_AGENT = "Mozilla/5.0 (compatible; HilvanaChat/1.0; vista previa de enlaces)"


class Blocked(Exception):
    """Dirección que no se pide (interna, protocolo o puerto raros…)."""


def _public_host(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise Blocked("el nombre no existe") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise Blocked("dirección interna")


def check_url(url: str) -> None:
    """Falla (Blocked) si la dirección no se puede pedir."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked("solo http y https")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise Blocked("puerto no válido") from exc
    if port not in (80, 443):
        raise Blocked("puerto no habitual")
    if parts.username or parts.password:
        raise Blocked("con usuario o contraseña")
    _public_host(parts.hostname, port)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # una redirección tampoco puede llevar a una dirección interna
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _get(url: str, accept: str, limit: int) -> tuple[bytes, str, str, str]:
    """Pide la dirección: (contenido hasta `limit` + 1 bytes, tipo, dirección final, juego de caracteres)."""
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "es-ES,es;q=0.9,en;q=0.5"})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        return (resp.read(limit + 1), resp.headers.get_content_type(), resp.geturl(),
                resp.headers.get_content_charset() or "")


class _Meta(HTMLParser):
    """Las etiquetas <meta> (Open Graph, Twitter, description) y el <title> de la página."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = " ".join(a["content"].split())
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


def _decode(body: bytes, charset: str) -> str:
    if not charset:
        head = body[:2048].decode("ascii", "ignore").lower()
        charset = "utf-8"
        if "charset=" in head:
            charset = head.split("charset=", 1)[1].split('"')[0].split("'")[0].split(";")[0].split(">")[0].strip() or "utf-8"
    try:
        return body.decode(charset, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def _image(url: str) -> str | None:
    """Miniatura como data: (PNG, JPG, WebP o GIF de hasta 150 KB), o None."""
    try:
        data, _, _, _ = _get(url, "image/*", MAX_IMAGE)
    except (Blocked, urllib.error.URLError, OSError, ValueError):
        return None
    mime = sniff_image(data) or ("image/gif" if data[:4] == b"GIF8" else None)
    if not mime or len(data) > MAX_IMAGE:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _fetch(url: str) -> dict | None:
    try:
        body, ctype, final, charset = _get(url, "text/html,application/xhtml+xml", MAX_PAGE)
    except (Blocked, urllib.error.URLError, OSError, ValueError) as exc:
        log.info("Sin vista previa de %s: %s", url, exc)
        return None
    if ctype not in ("text/html", "application/xhtml+xml"):
        return None
    parser = _Meta()
    try:
        parser.feed(_decode(body[:MAX_PAGE], charset))
    except Exception:  # noqa: BLE001 — HTML mal formado: vale lo leído
        pass
    meta = parser.meta
    title = meta.get("og:title") or meta.get("twitter:title") or " ".join(parser.title.split())
    if not title:
        return None
    image = meta.get("og:image") or meta.get("og:image:url") or meta.get("twitter:image")
    host = (urllib.parse.urlsplit(final).hostname or "").removeprefix("www.")
    return {
        "title": title[:200],
        "description": (meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or "")[:300],
        "site": (meta.get("og:site_name") or host)[:100],
        "image": _image(urllib.parse.urljoin(final, image)) if image else None,
    }


def preview(url: str) -> dict | None:
    """Título, descripción, sitio e imagen (data:) de la página, o None si no hay vista previa."""
    url = url.strip()
    if not url or len(url) > 2000:
        return None
    with get_conn() as conn:
        cached = repo.get(conn, url)
    if cached and (cached["ok"] or datetime.now() - datetime.fromisoformat(str(cached["fetched_at"])) < RETRY_AFTER):
        return {k: cached[k] for k in ("title", "description", "site", "image")} if cached["ok"] else None
    if not ENABLED:
        return None
    found = _fetch(url)
    with get_conn() as conn:
        repo.put(conn, url, found)
    return found
