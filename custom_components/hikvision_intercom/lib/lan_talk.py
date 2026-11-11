"""Hik-Connect app's local voice talk session with a station (command 0x200d on the control port), as an experiment.

Read from the app (libezstreamclient, CTalkClient): a TalkStart request on the control connection, whose socket then carries
the voice packets in both directions, each with a 24-byte header. This module only opens the session, plays a tone into it,
and logs what the station answers and sends, to find out what a real panel accepts.
"""

from __future__ import annotations

import logging
import math
import re
import select
import socket
import struct
import threading
import time
import uuid

from .lan_client import (
    CMD_INIT,
    INIT_SESSION_ID,
    PLACEHOLDER_OP_CODE,
    PORT_CTRL,
    _build_packet,
    _parse_response,
    _recv_response,
    _xml_init,
)

_LOGGER = logging.getLogger(__name__)

CMD_TALK_START = 0x200D
VOICE_HEADER_LEN = 24
VOICE_TYPE = 0x4100  # the packet type the app's InputTalkAudioData uses
_ULAW_BIAS = 0x84


def _ulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), 32635) + _ULAW_BIAS
    exponent = magnitude.bit_length() - 8
    return ~(sign | (exponent << 4) | ((magnitude >> (exponent + 3)) & 0x0F)) & 0xFF


def _tone_frames(seconds: float) -> list[bytes]:
    """A 440 Hz tone as 8 kHz mu-law, in 20 ms (160 byte) frames."""
    samples = [
        _ulaw(int(9000 * math.sin(2 * math.pi * 440 * n / 8000)))
        for n in range(int(seconds * 8000))
    ]
    data = bytes(samples)
    return [data[i : i + 160] for i in range(0, len(data) - 159, 160)]


def _xml_talk_start(serial: str, channel: int, encoding: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Request>\n"
        f"\t<OperationCode>{PLACEHOLDER_OP_CODE}</OperationCode>\n"
        f'\t<AudioInfo Channel="{channel}" Encoding="{encoding}" RelatedDevice="{serial}" />\n'
        f"\t<Uuid>{uuid.uuid4()}</Uuid>\n"
        f"\t<Timestamp>{int(time.time() * 1000)}</Timestamp>\n"
        "</Request>\n"
    ).encode()


def _voice_packet(session: int, payload: bytes) -> bytes:
    return (
        struct.pack(">HHI", VOICE_TYPE, VOICE_HEADER_LEN, 0)
        + struct.pack(">II", session, 0)
        + struct.pack(">II", len(payload), 0)
        + payload
    )


def probe_talk(
    host: str,
    serial: str,
    key: bytes,
    channel: int = 1,
    encoding: int = 1,
    seconds: float = 8.0,
) -> None:
    """Open a talk session, send a tone for a few seconds and log everything the station says. Never raises."""
    sock = None
    try:
        init = socket.create_connection((host, PORT_CTRL), timeout=5)
        try:
            init.sendall(_build_packet(1, CMD_INIT, _xml_init(INIT_SESSION_ID), key))
            _recv_response(init)
        finally:
            init.close()
        sock = socket.create_connection((host, PORT_CTRL), timeout=5)
        sock.sendall(
            _build_packet(
                1, CMD_TALK_START, _xml_talk_start(serial, channel, encoding), key
            )
        )
        meta, body = _parse_response(_recv_response(sock, timeout=8), key)
        text = body.decode("utf-8", "replace")
        _LOGGER.info(
            "Talk probe: answer cmd=0x%04x to TalkStart(encoding=%d): %s",
            meta["cmd"],
            encoding,
            re.sub(r"\s+", " ", text)[:400],
        )
        found = re.search(r"<Session>(\d+)</Session>", text)
        if not found:
            return
        session = int(found.group(1))
        stop = threading.Event()

        def speak() -> None:
            sent = 0
            for frame in _tone_frames(min(seconds, 4)):
                if stop.is_set():
                    break
                sock.sendall(_voice_packet(session, frame))
                sent += 1
                time.sleep(0.02)
            _LOGGER.info("Talk probe: sent %d tone frames", sent)

        speaker = threading.Thread(target=speak, daemon=True)
        speaker.start()
        received, heads, deadline = 0, [], time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([sock], [], [], 0.5)
            if not ready:
                continue
            chunk = sock.recv(65536)
            if not chunk:
                _LOGGER.info("Talk probe: the station closed the connection")
                break
            received += len(chunk)
            if len(heads) < 6:
                heads.append(f"{len(chunk)}B:{chunk[:32].hex()}")
        stop.set()
        speaker.join(timeout=2)
        _LOGGER.info(
            "Talk probe: received %d bytes in %.0f s; first chunks: %s",
            received,
            seconds,
            heads or "none",
        )
    except Exception as error:  # an experiment must never disturb the call
        _LOGGER.info("Talk probe failed: %s: %s", type(error).__name__, error)
    finally:
        if sock is not None:
            sock.close()
