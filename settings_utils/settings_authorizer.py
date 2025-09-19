import json
import base64
from Crypto.Cipher import AES

import logging
logger = logging.getLogger(__name__)

class DTSettingsAuthorizer:
    def __init__(self, key: bytes):
        self.key = key

    def sign_settings(self, settings: dict, serial: str) -> dict:
        """
        Sign the provided settings JSON with AES-CCM.
        The serial number is added into the JSON before signing.
        """
        # Add serial number into the settings
        settings_with_sn = dict(settings)
        settings_with_sn["sn"] = serial

        logger.debug(f"Signing content: {json.dumps(settings_with_sn)}")

        # Encode settings JSON as base64
        content = base64.b64encode(json.dumps(settings_with_sn).encode("utf-8"))

        # AES-CCM with fixed nonce (bytearray(13)) to match device
        c = AES.new(self.key, AES.MODE_CCM, nonce=bytearray(13))
        _ = c.encrypt(content)  # encrypt required even if not used
        tag = c.digest()

        signature = base64.b64encode(tag)

        return {
            "cnt": content.decode("utf-8"),
            "sig": signature.decode("utf-8")
        }
