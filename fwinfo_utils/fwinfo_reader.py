import binascii
import asyncio
from .protos import dt_fwinfo_pb2 as pb
import logging

logger = logging.getLogger(__name__)

FWINFO_MUX_ADDR = 0x12  # fwinfo0 channel

class FWInfoReader:
    def __init__(self):
        self._serial_future = asyncio.get_event_loop().create_future()

    async def handler(self, payload: bytes) -> None:
        try:
            resp = pb.CommandMessage.FromString(payload)
            if resp.HasField("res") and resp.res.HasField("dev_info"):
                dev_info = resp.res.dev_info
                logger.debug(f"Device serial number: {dev_info.serial_number}")

                if not self._serial_future.done():
                    self._serial_future.set_result(dev_info.serial_number)
            else:
                logger.error("Got response but no dev_info field.")
        except Exception as e:
            logger.error(f"Failed to parse FWINFO response: {e}")

    def build_request(self) -> bytes:
        msg = pb.CommandMessage()
        msg.req.cmd = pb.Command.READ_DEVICE_INFO
        msgSer = msg.SerializeToString()
        logger.debug(f"Sending FWINFO request: {binascii.hexlify(msgSer)}")
        return msgSer

    async def wait_serial(self) -> str:
        return await self._serial_future