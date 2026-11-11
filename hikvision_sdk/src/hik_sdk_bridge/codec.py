"""The codec a station sends and expects during a call, and the conversion to and from the 8 kHz G.711 mu-law the bridge's
clients use (``docs`` and the contract in ``server.py``), so a client never needs to know the station's encoding.

G.711 passes through. G.722.1 (16 kHz, 20 ms frames of 40, 60 or 80 bytes for 16, 24 or 32 kbit/s) goes through the Hikvision
SDK's own G.722 functions: this is a best guess at how they work (one frame in, one 20 ms frame of 16 kHz PCM16 out, and the
reverse) and it is *experimental*: it has not been checked against a real station, which is why every step is logged.
"""

from __future__ import annotations

import logging
import struct

from .g711 import mulaw_to_pcm16le, pcm16le_to_mulaw

_LOGGER = logging.getLogger(__name__)

G711 = "g711"
G722_1 = "g722_1"
AUTO = "auto"
ENCODINGS = (AUTO, G711, G722_1)

G711_FRAME = 160  # bytes of 20 ms of 8 kHz mu-law
PCM16K_FRAME = 640  # bytes of 20 ms of 16 kHz PCM16
G722_FRAME_SIZES = (
    80,
    60,
    40,
)  # bytes per 20 ms frame at 32, 24 and 16 kbit/s, the largest tried first
DEFAULT_G722_FRAME = 80


def g722_frame_size(chunk_length: int) -> int | None:
    """The G.722.1 frame size a chunk of this length is made of (the largest that divides it), or None."""
    return next(
        (
            size
            for size in G722_FRAME_SIZES
            if chunk_length and chunk_length % size == 0
        ),
        None,
    )


def downsample(pcm16k: bytes) -> bytes:
    """16 kHz PCM16 to 8 kHz: each pair of samples is averaged, which is also a gentle low-pass."""
    samples = struct.unpack(f"<{len(pcm16k) // 2}h", pcm16k[: len(pcm16k) // 2 * 2])
    pairs = (len(samples) // 2) * 2
    return struct.pack(
        f"<{pairs // 2}h",
        *((samples[i] + samples[i + 1]) // 2 for i in range(0, pairs, 2)),
    )


def upsample(pcm8k: bytes) -> bytes:
    """8 kHz PCM16 to 16 kHz by linear interpolation."""
    samples = struct.unpack(f"<{len(pcm8k) // 2}h", pcm8k)
    out: list[int] = []
    for index, sample in enumerate(samples):
        following = samples[index + 1] if index + 1 < len(samples) else sample
        out.extend((sample, (sample + following) // 2))
    return struct.pack(f"<{len(out)}h", *out)


class PassThrough:
    """G.711 mu-law station: nothing to convert."""

    name = G711

    def from_station(self, data: bytes) -> bytes:
        return data

    def to_station(self, frame: bytes) -> bytes:
        return frame

    def close(self) -> None:
        pass


class G722Codec:
    """G.722.1 station, through the SDK's codec functions. Not checked against a real station."""

    name = G722_1

    def __init__(self, sdk) -> None:
        self._sdk = sdk
        self._frame: int | None = None
        self._decoder = None
        self._encoder = None
        self._pending = b""
        self._decoded = 0
        self._encoded = 0

    @property
    def frame_bytes(self) -> int:
        return self._frame or DEFAULT_G722_FRAME

    def _open_decoder(self, chunk_length: int) -> None:
        frame = g722_frame_size(chunk_length)
        if frame is None:
            raise ValueError(
                f"a {chunk_length} byte chunk is not made of 40, 60 or 80 byte G.722.1 frames"
            )
        self._frame = frame
        self._decoder = self._sdk.g722_decoder_open(
            frame * 8 * 50
        )  # bit/s: 20 ms frames, 50 a second
        _LOGGER.info(
            "G.722.1: decoding %d byte frames (%d bit/s guessed from the chunk size)",
            frame,
            frame * 400,
        )

    def from_station(self, data: bytes) -> bytes:
        """The station's G.722.1 to 8 kHz mu-law (a whole number of 160 byte frames)."""
        if self._decoder is None:
            self._open_decoder(len(data))
        self._pending += data
        out = bytearray()
        while len(self._pending) >= self._frame:
            frame, self._pending = (
                self._pending[: self._frame],
                self._pending[self._frame :],
            )
            pcm = self._sdk.g722_decode(self._decoder, frame)
            if self._decoded == 0:
                _LOGGER.info(
                    "G.722.1: the first decoded frame is %d bytes of PCM (%d expected)",
                    len(pcm),
                    PCM16K_FRAME,
                )
            self._decoded += 1
            out += pcm16le_to_mulaw(downsample(pcm))
        return bytes(out)

    def to_station(self, frame: bytes) -> bytes:
        """160 bytes of 8 kHz mu-law to one G.722.1 frame for the station."""
        if self._encoder is None:
            self._encoder = self._sdk.g722_encoder_open()
            _LOGGER.info(
                "G.722.1: encoding %d byte frames for the station", self.frame_bytes
            )
        encoded = self._sdk.g722_encode(
            self._encoder, upsample(mulaw_to_pcm16le(frame)), self.frame_bytes
        )
        if self._encoded == 0:
            _LOGGER.info("G.722.1: the first encoded frame is %d bytes", len(encoded))
        self._encoded += 1
        return encoded

    def close(self) -> None:
        decoder, encoder, self._decoder, self._encoder = (
            self._decoder,
            self._encoder,
            None,
            None,
        )
        if decoder is not None:
            self._sdk.g722_decoder_close(decoder)
        if encoder is not None:
            self._sdk.g722_encoder_close(encoder)
        _LOGGER.info(
            "G.722.1: %d frames decoded, %d encoded", self._decoded, self._encoded
        )
