"""A scriptable stand-in for the loaded SDK, used above the ctypes boundary."""

from hik_sdk_bridge.sdk import SdkError


class FakeSdk:
    def __init__(self):
        self.login_error = None
        self.call = "idle"
        self.call_error = None
        self.voice_error = None
        self.send_error_after = None
        self.logins = 0
        self.logouts = []
        self.frames = []
        self.voice_started = 0
        self.voice_channels = []
        self.voice_stopped = []
        self.on_audio = None
        self.encoding_code = 1  # what the station says its audio is encoded in (1: G.711 mu-law, 0: G.722.1, None: unknown)
        self.g722_decoded = []
        self.g722_encoded = []
        self.g722_decoder_bitrates = []
        self.g722_released = []

    def login(self, host, port, username, password):
        if self.login_error:
            raise SdkError("login", self.login_error)
        self.logins += 1
        return 7, "SERIAL123"

    def logout(self, user_id):
        self.logouts.append(user_id)

    def call_state(self, user_id):
        if self.call_error:
            raise SdkError("call status", self.call_error)
        return self.call

    def start_voice(self, user_id, on_audio=None, channel=1):
        self.voice_channels.append(channel)
        if self.voice_error:
            raise SdkError("start voice", self.voice_error)
        self.voice_started += 1
        self.on_audio = on_audio
        return 99

    def deliver(self, data):
        """What the SDK thread does when the door sends audio."""
        self.on_audio(data)

    def send_voice(self, handle, frame):
        if (
            self.send_error_after is not None
            and len(self.frames) >= self.send_error_after
        ):
            raise SdkError("send voice", 12)
        self.frames.append(bytes(frame))

    def audio_encoding(self, user_id):
        return self.encoding_code, "fake"

    def g722_decoder_open(self, bitrate):
        self.g722_decoder_bitrates.append(bitrate)
        return 11

    def g722_decode(self, handle, frame):
        self.g722_decoded.append(bytes(frame))
        return b"\x10\x00" * 320  # 20 ms of 16 kHz PCM16: a constant level

    def g722_decoder_close(self, handle):
        self.g722_released.append(("decoder", handle))

    def g722_encoder_open(self):
        return 12

    def g722_encode(self, handle, pcm16k, frame_bytes):
        self.g722_encoded.append(bytes(pcm16k))
        return bytes([0xAB]) * frame_bytes

    def g722_encoder_close(self, handle):
        self.g722_released.append(("encoder", handle))

    def voice_stats(self, handle):
        return (
            {1: [len(self.frames), sum(len(f) for f in self.frames)]}
            if self.frames
            else {}
        )

    def stop_voice(self, handle):
        self.voice_stopped.append(handle)
