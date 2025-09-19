import asyncio
import json
import base64
import logging
import serial_asyncio

from .config import MUX_PATH, BAUDRATE, SETTINGS_MUX_ADDR, SMP_SRV_MUX_ADDR, RESTART_CMD, AUTH_KEY
from .slip_utils.slip_dispatcher import SlipDispatcher, Slip
from .settings_utils.settings_handler import SettingsHandler
from .settings_utils.settings_authorizer import DTSettingsAuthorizer
from .fwinfo_utils.fwinfo_reader import FWInfoReader, FWINFO_MUX_ADDR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def restart_device(transport: serial_asyncio.SerialTransport):
    restart_request = bytes([SMP_SRV_MUX_ADDR]) + bytes(RESTART_CMD)
    encoded_request = Slip.encode(restart_request)
    transport.write(encoded_request)

def read_settings(transport: serial_asyncio.SerialTransport):
    """Read settings by sending '{}' (empty json) command."""
    read_request = bytes([SETTINGS_MUX_ADDR]) + b"{}"
    transport.write(Slip.encode(read_request))

async def upload_settings(transport, handler, payload: dict, verify_dict: dict | None = None):
    """Helper: send JSON payload, wait for response, and optionally verify."""
    json_bytes = json.dumps(payload).encode("utf-8")
    packet = bytes([SETTINGS_MUX_ADDR]) + json_bytes
    encoded = Slip.encode(packet)
    transport.write(encoded)
    
    await asyncio.sleep(0.2) # device needs processing time

    # follow with a read request to fetch back config
    read_settings(transport)

    received = await handler.wait_response()
    if not received:
        logger.error("No JSON received from device")
        return False

    if verify_dict:
        if handler.verify(verify_dict, received):
            logger.info("Verification OK for %s", list(verify_dict.keys()))
            return True
        else:
            logger.error("Verification failed for %s", list(verify_dict.keys()))
            return False

    return True


async def main():
    dispatcher = SlipDispatcher()
    settings_handler = SettingsHandler()
    fwinfo = FWInfoReader()

    dispatcher.register_handler(SETTINGS_MUX_ADDR, settings_handler.handle)
    dispatcher.register_handler(FWINFO_MUX_ADDR, fwinfo.handler)

    transport, _ = await dispatcher.start(MUX_PATH, baudrate=BAUDRATE)
    logger.info(f"Connected to {MUX_PATH} at {BAUDRATE} baud")

    # 1. Read current settings
    read_settings(transport)
    received = await settings_handler.wait_response()

    if not received:
        logger.error("No JSON received on initial read")
        transport.close()
        return

    is_locked = received.get("settings/lock", False)
    if not is_locked:
        logger.info("Device is unlocked, running init setup to lock the device.")

        # 2a. Set acl_0 and key_0
        key = bytes(AUTH_KEY)
        setup_access_settings = {
            "settings/acl_0": "//////////////////////////////////////////8=",  # all-access for key_0
            "settings/key_0": base64.b64encode(key).decode("utf-8"),
            "save": True,
        }
        ok = await upload_settings(transport, settings_handler, setup_access_settings,
                                   verify_dict=setup_access_settings)
        if not ok:
            logger.error("Failed to prepare ACL/key on unlocked device")
            transport.close()
            return

        # 2b. Lock the device
        lock_settings = {"settings/lock": True, "save": True}
        ok = await upload_settings(transport, settings_handler, lock_settings,
                                   verify_dict=lock_settings)
        if not ok:
            logger.error("Failed to lock device")
            transport.close()
            return

        logger.info("Device successfully locked")

    else:
        logger.info("Device is already locked, continuing with signed settings")

    # --- 3. Signed settings flow ---
    key = bytes(AUTH_KEY)
    authorizer = DTSettingsAuthorizer(key)

    # get device serial
    msgSer = fwinfo.build_request()
    transport.write(Slip.encode(bytes([FWINFO_MUX_ADDR]) + msgSer))
    serial = await fwinfo.wait_serial()
    logger.info(f"Using serial: {serial}")

    # example settings to send
    settings_to_send = {
        "app/brightness": 25,
        "save": True
        }
    signed_settings = authorizer.sign_settings(settings_to_send, serial)

    await upload_settings(transport, settings_handler, signed_settings,
                          verify_dict=settings_to_send)


    # Finally restart the device to ensure the configuration settings are applied
    restart_device(transport)
    logger.info("Restart command sent, waiting for device to come back...")

    transport.close()

    # Try to reconnect
    for i in range(10):
        await asyncio.sleep(1.0)
        try:
            transport, _ = await dispatcher.start(MUX_PATH, baudrate=BAUDRATE)
            logger.info("Reconnected to device, checking settings...")
            read_settings(transport)
            received = await settings_handler.wait_response()
            if received:
                logger.info("Device restarted successfully")
                break
        except Exception as e:
            logger.debug(f"Reconnect attempt failed: {e}")
    else:
        logger.error("Device restart timed out")


    transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
