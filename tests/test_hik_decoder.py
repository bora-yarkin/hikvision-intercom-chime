def test_describe_stream_counts_packets_per_channel_and_payload_type():
    from custom_components.hikvision_intercom.lib.hik_decoder import describe_stream

    def frame(channel, payload_type):
        packet = bytes(12) + bytes([13, payload_type]) + bytes(14)
        return bytes([0x24, channel]) + len(packet).to_bytes(2, "big") + packet

    text = describe_stream(frame(1, 96) * 2 + frame(3, 0))
    assert "channel 1 nested payload type 96: 2 packets" in text
    assert "channel 3 nested payload type 0: 1 packets" in text
    assert describe_stream(b"nothing here") == "no interleaved packets found"
