"""Notas de voz grabadas en el navegador.

Chrome y Edge graban en WebM, Firefox en Ogg (los dos con el códec Opus) y Safari en MP4 (AAC). WhatsApp y Telegram
quieren las notas de voz en Ogg/Opus, así que lo grabado en WebM se pasa a Ogg sin recodificar: se sacan los paquetes
Opus del WebM (Matroska) y se meten en páginas Ogg, como dice la RFC 7845. El MP4 se envía tal cual (como audio)."""
import os
import struct

from .errors import InvalidInput

# Elementos de Matroska/WebM que hacen falta
SEGMENT, CLUSTER, TRACKS, TRACK_ENTRY, BLOCK_GROUP = 0x18538067, 0x1F43B675, 0x1654AE6B, 0xAE, 0xA0
SIMPLE_BLOCK, BLOCK, TRACK_NUMBER, CODEC_ID, CODEC_PRIVATE = 0xA3, 0xA1, 0xD7, 0x86, 0x63A2
DESCEND = {SEGMENT, CLUSTER, TRACKS, BLOCK_GROUP}  # contenedores que se recorren por dentro (pueden no tener tamaño)
UNKNOWN = -1

# Muestras (a 48 kHz) de cada trama Opus según la configuración del primer byte del paquete (RFC 6716, 3.1)
FRAME_SAMPLES = [480, 960, 1920, 2880] * 3 + [480, 960] * 2 + [120, 240, 480, 960] * 4
VENDOR = b"Hilvana Chat"
PAGE_MAX_PACKETS = 50  # unas pocas decenas de paquetes por página (1 s de audio con tramas de 20 ms)


def _vint(data: bytes, pos: int, keep_marker: bool) -> tuple[int, int]:
    """Entero de longitud variable de EBML: el identificador de un elemento (con su marca) o su tamaño (sin ella;
    todo unos = tamaño desconocido)."""
    first = data[pos]
    length, mask = 1, 0x80
    while length <= 8 and not first & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("entero de EBML no válido")
    value = first if keep_marker else first & (mask - 1)
    for byte in data[pos + 1:pos + length]:
        value = (value << 8) | byte
    if not keep_marker and value == (1 << (7 * length)) - 1:
        value = UNKNOWN
    return value, pos + length


def _track_entry(data: bytes, start: int, end: int) -> dict:
    """Número, códec y datos del códec de una pista."""
    track, pos = {}, start
    while pos < end:
        el_id, pos = _vint(data, pos, True)
        size, pos = _vint(data, pos, False)
        if size == UNKNOWN:
            break
        body = data[pos:pos + size]
        if el_id == TRACK_NUMBER:
            track["number"] = int.from_bytes(body, "big")
        elif el_id == CODEC_ID:
            track["codec"] = body.decode("ascii", "replace")
        elif el_id == CODEC_PRIVATE:
            track["private"] = bytes(body)
        pos += size
    return track


def _opus_from_webm(data: bytes) -> tuple[bytes | None, list[bytes]]:
    """La cabecera Opus (OpusHead) y los paquetes Opus de la pista de audio, en orden."""
    head, opus_track, packets, pos = None, None, [], 0
    while pos < len(data):
        try:
            el_id, pos = _vint(data, pos, True)
            size, pos = _vint(data, pos, False)
        except (IndexError, ValueError):
            break  # el final del archivo está cortado: vale lo leído hasta ahí
        if el_id in DESCEND:
            continue
        if size == UNKNOWN:
            break
        if el_id == TRACK_ENTRY:
            track = _track_entry(data, pos, pos + size)
            if track.get("codec") == "A_OPUS" and opus_track is None:
                opus_track, head = track.get("number"), track.get("private")
        elif el_id in (SIMPLE_BLOCK, BLOCK):
            number, start = _vint(data, pos, False)
            flags = data[start + 2]
            if (flags >> 1) & 3:
                raise InvalidInput("La nota de voz viene en un formato que no se puede convertir.")
            if number == opus_track and pos + size > start + 3:
                packets.append(bytes(data[start + 3:pos + size]))
        pos += size
    return head, packets


def _samples(packet: bytes) -> int:
    """Duración del paquete Opus, en muestras a 48 kHz."""
    toc = packet[0]
    code = toc & 3
    frames = 1 if code == 0 else 2 if code in (1, 2) else (packet[1] & 0x3F if len(packet) > 1 else 0)
    return FRAME_SAMPLES[toc >> 3] * frames


def _crc_table() -> list[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else r << 1
        table.append(r & 0xFFFFFFFF)
    return table


CRC_TABLE = _crc_table()


def _ogg_crc(page: bytes) -> int:
    crc = 0
    for byte in page:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]
    return crc


def _page(serial: int, sequence: int, granule: int, packets: list[bytes], header_type: int) -> bytes:
    """Una página Ogg con esos paquetes completos (granule: muestras decodificadas hasta el final de la página)."""
    lacing = bytearray()
    for p in packets:
        lacing += b"\xff" * (len(p) // 255) + bytes([len(p) % 255])
    page = struct.pack("<4sBBqIIIB", b"OggS", 0, header_type, granule, serial, sequence, 0, len(lacing)) \
        + bytes(lacing) + b"".join(packets)
    return page[:22] + struct.pack("<I", _ogg_crc(page)) + page[26:]


def webm_to_ogg(data: bytes) -> bytes:
    """Pasa una grabación WebM/Opus a Ogg/Opus, sin recodificar."""
    head, packets = _opus_from_webm(data)
    packets = [p for p in packets if p]
    if not packets:
        raise InvalidInput("La nota de voz está vacía o no se pudo leer.")
    if not head or not head.startswith(b"OpusHead"):
        head = struct.pack("<8sBBHIhB", b"OpusHead", 1, 1, 312, 48000, 0, 0)
    serial = int.from_bytes(os.urandom(4), "little")
    tags = b"OpusTags" + struct.pack("<I", len(VENDOR)) + VENDOR + struct.pack("<I", 0)
    pages = [_page(serial, 0, 0, [head], 0x02), _page(serial, 1, 0, [tags], 0x00)]
    batch, lacing, total = [], 0, 0
    for p in packets:
        need = len(p) // 255 + 1
        if batch and (lacing + need > 255 or len(batch) >= PAGE_MAX_PACKETS):
            pages.append(_page(serial, len(pages), total, batch, 0x00))
            batch, lacing = [], 0
        batch.append(p)
        lacing += need
        total += _samples(p)
    pages.append(_page(serial, len(pages), total, batch, 0x04))  # la última, con la marca de fin
    return b"".join(pages)


def for_sending(data: bytes, mime: str | None) -> tuple[bytes, str]:
    """El audio listo para enviar como nota de voz y su tipo: Ogg/Opus (lo de WebM se convierte) o MP4 (Safari)."""
    base = (mime or "").split(";")[0].strip().lower()
    if data[:4] == b"\x1a\x45\xdf\xa3" or base == "audio/webm":
        return webm_to_ogg(data), "audio/ogg"
    if data[:4] == b"OggS" or base == "audio/ogg":
        return data, "audio/ogg"
    if base in ("audio/mp4", "audio/aac", "audio/x-m4a"):
        return data, "audio/mp4"
    raise InvalidInput("Ese formato de audio no se puede enviar como nota de voz.")
