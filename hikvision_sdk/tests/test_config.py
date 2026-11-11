import json

import pytest

from hik_sdk_bridge import config

TOKEN = "t" * 40
STATION = {
    "name": "hall",
    "host": "192.168.0.50",
    "port": 8000,
    "username": "admin",
    "password": "secret-pass",
}


def test_valid_options():
    parsed = config.parse({"token": TOKEN, "stations": [STATION]})
    assert parsed.stations[0].host == "192.168.0.50"
    assert parsed.stations[0].port == 8000


def test_secrets_are_not_in_repr():
    parsed = config.parse({"token": TOKEN, "stations": [STATION]})
    assert "secret-pass" not in repr(parsed) and TOKEN not in repr(parsed)


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Bad Name"},
        {"name": ""},
        {"name": "../x"},
        {"host": "8.8.8.8"},
        {"host": "example.com"},
        {"host": "192.168.0.999"},
        {"port": 0},
        {"port": 70000},
        {"port": True},
        {"port": "8000"},
        {"username": ""},
        {"password": ""},
        {"password": "x" * 65},
        {"password": "a\nb"},
    ],
)
def test_invalid_station_is_rejected(change):
    with pytest.raises(config.ConfigError):
        config.parse({"token": TOKEN, "stations": [dict(STATION, **change)]})


@pytest.mark.parametrize("token", [None, "", "short", "x" * 129, 12])
def test_invalid_token_is_rejected(token):
    with pytest.raises(config.ConfigError):
        config.parse({"token": token, "stations": []})


def test_duplicate_station_names_are_rejected():
    with pytest.raises(config.ConfigError):
        config.parse({"token": TOKEN, "stations": [STATION, STATION]})


def test_error_messages_never_contain_values():
    try:
        config.parse({"token": TOKEN, "stations": [dict(STATION, password="")]})
    except config.ConfigError as error:
        assert "secret" not in str(error)


def test_load_reads_file_and_rejects_garbage(tmp_path):
    good = tmp_path / "options.json"
    good.write_text(json.dumps({"token": TOKEN, "stations": []}))
    assert config.load(good).stations == ()
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    with pytest.raises(config.ConfigError):
        config.load(bad)
    with pytest.raises(config.ConfigError):
        config.load(tmp_path / "missing.json")


def test_audio_encoding_defaults_to_auto_and_accepts_the_three_choices():
    from hik_sdk_bridge.config import ConfigError, parse

    base = {"token": "t" * 40, "stations": []}
    assert parse(base).audio_encoding == "auto"
    for choice in ("auto", "g711", "g722_1"):
        assert parse({**base, "audio_encoding": choice}).audio_encoding == choice
    with pytest.raises(ConfigError):
        parse({**base, "audio_encoding": "mp3"})


def test_voice_channel_defaults_to_1_and_must_be_a_number_from_1_to_32():
    from hik_sdk_bridge.config import ConfigError, parse

    base = {"token": "t" * 40, "stations": []}
    assert parse(base).voice_channel == 1
    assert parse({**base, "voice_channel": 2}).voice_channel == 2
    for bad in (0, 33, "2", True, 1.5):
        with pytest.raises(ConfigError):
            parse({**base, "voice_channel": bad})
