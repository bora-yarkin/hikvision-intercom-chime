"""G.722.1 through the SDK's codec functions (experimental) and the conversions around it."""

import struct

import pytest
from fakes import FakeSdk

from hik_sdk_bridge.codec import (
    G722Codec,
    PassThrough,
    downsample,
    g722_frame_size,
    upsample,
)
from hik_sdk_bridge.g711 import mulaw_to_pcm16le, pcm16le_to_mulaw


@pytest.mark.parametrize(
    ("length", "frame"),
    [
        (80, 80),
        (160, 80),
        (60, 60),
        (120, 60),
        (40, 40),
        (100, None),
        (0, None),
        (7, None),
        (170, None),
    ],
)
def test_the_frame_size_is_the_largest_that_divides_the_chunk(length, frame):
    assert g722_frame_size(length) == frame


def test_downsampling_averages_pairs_and_halves_the_length():
    pcm = struct.pack("<4h", 100, 300, -50, 50)
    assert struct.unpack("<2h", downsample(pcm)) == (200, 0)


def test_upsampling_interpolates_and_doubles_the_length():
    pcm = struct.pack("<3h", 0, 100, 200)
    assert struct.unpack("<6h", upsample(pcm)) == (0, 50, 100, 150, 200, 200)


def test_mulaw_decoding_inverts_encoding_within_the_codec_precision():
    pcm = struct.pack("<5h", 0, 1000, -1000, 20000, -20000)
    back = struct.unpack("<5h", mulaw_to_pcm16le(pcm16le_to_mulaw(pcm)))
    assert all(
        abs(a - b) <= max(40, abs(a) // 16)
        for a, b in zip((0, 1000, -1000, 20000, -20000), back, strict=True)
    )


def test_pass_through_changes_nothing():
    codec = PassThrough()
    assert codec.from_station(b"abc") == b"abc" and codec.to_station(b"xyz") == b"xyz"


def test_g722_chunks_become_whole_160_byte_mulaw_frames_and_the_bitrate_follows_the_chunk_size():
    sdk = FakeSdk()
    codec = G722Codec(sdk)
    out = codec.from_station(bytes(range(80)) * 2)  # two 32 kbit/s frames in one chunk
    assert (
        len(out) == 320
        and len(sdk.g722_decoded) == 2
        and sdk.g722_decoder_bitrates == [32000]
    )
    codec2 = G722Codec(FakeSdk())
    codec2.from_station(bytes(60))
    assert codec2._sdk.g722_decoder_bitrates == [24000] and codec2.frame_bytes == 60


def test_a_partial_g722_frame_waits_for_the_rest():
    sdk = FakeSdk()
    codec = G722Codec(sdk)
    assert codec.from_station(bytes(80)) != b""
    sdk2 = FakeSdk()
    codec = G722Codec(sdk2)
    codec.from_station(bytes(40) + bytes(40))  # opens at frame size 80
    assert len(sdk2.g722_decoded) == 1


def test_a_chunk_that_is_no_g722_frame_is_refused_before_the_sdk_is_used():
    sdk = FakeSdk()
    with pytest.raises(ValueError):
        G722Codec(sdk).from_station(bytes(170))
    assert sdk.g722_decoder_bitrates == []


def test_talking_encodes_20_ms_of_16k_pcm_into_one_station_frame():
    sdk = FakeSdk()
    codec = G722Codec(sdk)
    frame = codec.to_station(bytes([0xFF]) * 160)
    assert len(sdk.g722_encoded[0]) == 640 and frame == bytes([0xAB]) * 80


def test_close_releases_the_codecs_it_opened():
    sdk = FakeSdk()
    codec = G722Codec(sdk)
    codec.from_station(bytes(80))
    codec.to_station(bytes([0xFF]) * 160)
    codec.close()
    assert sorted(sdk.g722_released) == [("decoder", 11), ("encoder", 12)]
    codec.close()  # safe to repeat
    assert len(sdk.g722_released) == 2
