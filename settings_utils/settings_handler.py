import asyncio
import json
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class SettingsHandler:
    """
    Async handler for reading/writing settings over SLIP.
    Reassembles multi-chunk JSON responses and allows verification.
    """

    def __init__(self):
        self.buffer = ""
        self.brace_count = 0
        self.in_json = False
        self.response_future: Optional[asyncio.Future] = None

    async def handle(self, payload: bytes):
        """
        Async callback for incoming SLIP packets for the settings channel.
        Reassembles JSON split across multiple packets.
        """
        chunk = payload.decode("utf-8", errors="replace")
        logger.debug(f"RX chunk: {chunk}")
        self.buffer += chunk

        # Update brace count for JSON reassembly
        for ch in chunk:
            if ch == '{':
                self.brace_count += 1
                self.in_json = True
            elif ch == '}':
                self.brace_count -= 1

        # Complete JSON received
        if self.in_json and self.brace_count == 0:
            try:
                json_obj = json.loads(self.buffer)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                json_obj = None

            # Set the result to unblock waiting coroutine
            if self.response_future and not self.response_future.done():
                self.response_future.set_result(json_obj)

            # Reset buffer for next response
            self.buffer = ""
            self.in_json = False

    async def wait_response(self, timeout: float = 2.0):
        """
        Wait for a complete JSON response to be received.
        """
        self.response_future = asyncio.get_running_loop().create_future()
        try:
            return await asyncio.wait_for(self.response_future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for settings response")
            return None

    def verify(self, expected: dict, received: dict) -> bool:
        """
        Verifies if received settings match the expected values.
        Skips write-only keys like 'save' and 'reset'.
        """
        if not received:
            return False

        excluded_keys = ["save", "reset", "settings/key_0", "settings/key_1", "settings/key_2"]
        is_verified = True

        for key, value in expected.items():
            if key in excluded_keys:
                continue

            if key in received:
                received_value = received[key]
                logger.info(f"Device returned '{key}' = {received_value}")
                if received_value != value:
                    logger.error(f"Mismatch: expected {value}, got {received_value}")
                    is_verified = False
            else:
                logger.error(f"Key '{key}' missing in device response")
                is_verified = False

        return is_verified
