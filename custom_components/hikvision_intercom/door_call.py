"""Talking and listening during a door call, through the SDK bridge app."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager

from homeassistant.core import HomeAssistant

from .bridge_client import BridgeError
from .call_audio import speech_frames
from .chime import ChimeRuntime
from .const import DOMAIN
from .hikconnect_api import HikConnectError
from .lib.lan_talk import probe_talk

_LOGGER = logging.getLogger(__name__)
ANSWER_WAIT_SECONDS = 5.0


class DoorCall:
    """One station's call audio. ``talk`` answers a ringing call first (the person speaking means to take it)."""

    def __init__(self, hass: HomeAssistant, entry_id: str, chime: ChimeRuntime) -> None:
        self._hass, self._entry_id, self._chime = hass, entry_id, chime
        self._lock = asyncio.Lock()
        self._probing = False

    @property
    def name(self) -> str:
        return self._chime.station_name

    @property
    def serial(self) -> str | None:
        """The cloud device that rings with this station, when it is known."""
        return self._chime.device_serial

    async def _state(self) -> str:
        status = await self._chime.link.call(lambda client: client.status(self.name))
        return status.get("call_status", "unknown")

    async def _answer(self) -> None:
        serial = self._chime.device_serial
        cloud = (self._hass.data.get(DOMAIN, {}).get(self._entry_id) or {}).get(
            "client"
        )
        if serial is None or cloud is None:
            raise BridgeError(
                "no_call"
            )  # which cloud device rings is not known, so nothing is answered blindly
        try:
            await self._hass.async_add_executor_job(cloud.answer_call, serial)
        except HikConnectError:
            raise BridgeError("answer_failed") from None

    async def _in_call(self) -> None:
        state = await self._state()
        _LOGGER.info("Door audio: the station says the call is %s", state)
        if state == "ringing":
            _LOGGER.info("Door audio: answering the ringing call through the cloud")
            await self._answer()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + ANSWER_WAIT_SECONDS
            while state != "in_call" and loop.time() < deadline:
                await asyncio.sleep(0.5)
                state = await self._state()
        if state != "in_call":
            raise BridgeError("no_call")

    async def lan_talk_probe(self) -> None:
        """Experiment: open the Hik-Connect app's local talk session once per call and log what the panel does."""
        if self._probing:
            return
        self._probing = True
        try:
            entry = self._hass.data.get(DOMAIN, {}).get(self._entry_id) or {}
            serial, client = self._chime.device_serial, entry.get("client")
            status = (entry.get("status_coordinator").data or {}).get(serial) or {}
            host = status.get("local_ip")
            if not (serial and client and host):
                _LOGGER.info("Talk probe: no cloud device or LAN address known")
                return
            key, _ = await self._hass.async_add_executor_job(
                client.get_control_key, serial
            )
            await self._hass.async_add_executor_job(
                probe_talk, host, serial, key.encode("ascii")
            )
        except Exception as error:
            _LOGGER.info("Talk probe not run: %s: %s", type(error).__name__, error)
        finally:
            self._probing = False

    async def talk(self, stream: AsyncIterable[bytes]) -> int:
        """Speech (16 kHz PCM, as Assist delivers it) into the call; returns the 20 ms frames sent."""
        if self._lock.locked():
            raise BridgeError("busy")
        async with self._lock:
            await self._in_call()
            client = await self._chime.link.client()
            try:
                return await client.talk(self.name, speech_frames(stream))
            except BridgeError as error:
                if error.code in ("app_unreachable", "app_unauthorized"):
                    self._chime.link.invalidate()
                raise

    @asynccontextmanager
    async def listen(self):
        """The door's audio (raw mu-law chunks) for as long as the call lasts."""
        client = await self._chime.link.client()
        try:
            async with client.listen(self.name) as chunks:
                yield chunks
        except BridgeError as error:
            if error.code in ("app_unreachable", "app_unauthorized"):
                self._chime.link.invalidate()
            raise
