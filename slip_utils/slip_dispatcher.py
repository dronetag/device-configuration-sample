import argparse
import asyncio
import binascii
import serial_asyncio
from typing import Callable, Dict, List, Awaitable, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class Slip:
    END = 0x0A
    ESC = 0xDB
    ESC_END = 0xDC
    ESC_ESC = 0xDD

    END_b = b"\n"
    ESC_b = b"\xdb"
    ESC_END_b = b"\xdc"
    ESC_ESC_b = b"\xdd"

    @staticmethod
    def encode(data: bytes) -> bytes:
        return (
            data.replace(Slip.ESC_b, Slip.ESC_b + Slip.ESC_ESC_b)
                .replace(Slip.END_b, Slip.ESC_b + Slip.ESC_END_b)
            + Slip.END_b
        )

    @staticmethod
    def decode(data: bytes) -> bytes:
        return (
            data.replace(Slip.ESC_b + Slip.ESC_ESC_b, Slip.ESC_b)
                .replace(Slip.ESC_b + Slip.ESC_END_b, Slip.END_b)
        ).strip(Slip.END_b)


HandlerType = Callable[[bytes], Awaitable[None]]


class SlipSerialReader(asyncio.Protocol):
    def __init__(self, handler_map: Dict[int, List[HandlerType]]) -> None:
        self.buffer = bytearray()
        self.transport: Optional[asyncio.Transport] = None
        self.handler_map = handler_map

    def connection_made(self, transport: asyncio.Transport) -> None:
        self.transport = transport
        port = transport.get_extra_info('serial')
        logger.info(f"Connected to {port.port}")

    def data_received(self, data: bytes) -> None:
        self.buffer.extend(data)
        while Slip.END in self.buffer:
            end_index = self.buffer.index(Slip.END)
            raw_packet = bytes(self.buffer[:end_index + 1])
            self.buffer = self.buffer[end_index + 1:]
            asyncio.create_task(self.process_packet(raw_packet))

    async def process_packet(self, packet: bytes) -> None:
        try:
            decoded = Slip.decode(packet)
            if not decoded:
                return
            address = decoded[0]
            payload = decoded[1:]
            handlers = self.handler_map.get(address, [])
            logger.debug(f"Received data on address: {address:#02x}")
            if handlers:
                await asyncio.gather(*(handler(payload) for handler in handlers))
        except Exception as e:
            logger.error(f"Error processing packet: {e}")

class SlipDispatcher:
    def __init__(self) -> None:
        self.handler_map: Dict[int, List[HandlerType]] = {}

    def register_handler(self, address: int, handler: HandlerType) -> None:
        if address not in self.handler_map:
            self.handler_map[address] = []

        self.handler_map[address].append(handler)

    async def start(self, port: str, baudrate: int = 115200) -> Tuple[serial_asyncio.SerialTransport, SlipSerialReader]:
        loop = asyncio.get_running_loop()
        transport, protocol = await serial_asyncio.create_serial_connection(
            loop,
            lambda: SlipSerialReader(self.handler_map),
            port,
            baudrate
        )
        return transport, protocol

class ProtobufDelimitedBuffer:
    def __init__(self, consumer: Callable[[bytes], Awaitable[None]]):
        self.buffer = bytearray()
        self.consumer = consumer

    async def feed(self, data: bytes):
        self.buffer.extend(data)
        while True:
            msg, remaining = self._extract_next_message(self.buffer)
            if msg is None:
                break  # incomplete message, wait for more data
            self.buffer = remaining
            await self.consumer(msg)
    
    def _read_varint(self, buf: bytearray) -> Tuple[int, int]:
        """Returns (value, length of varint)"""
        result = 0
        shift = 0
        for i, byte in enumerate(buf):
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                return result, i + 1
            shift += 7
        raise ValueError("Incomplete varint")


    def _extract_next_message(self, buf: bytearray) -> Tuple[Optional[bytes], bytearray]:
        try:
            size, size_len = self._read_varint(buf)
            if len(buf) < size_len + size:
                return None, buf  # incomplete payload
            msg_start = size_len
            msg_end = size_len + size
            msg = bytes(buf[msg_start:msg_end])
            return msg, buf[msg_end:]
        except Exception:
            return None, buf  # malformed or incomplete

async def handler1(payload: bytes) -> None:
    logger.debug(f"[Handler1] Payload: {payload!r}")

async def handler2(payload: bytes) -> None:
    logger.debug(f"[Handler2] Payload length: {len(payload)}")

async def main():
    parser = argparse.ArgumentParser(description="Async SLIP Serial Reader with Handler Dispatch")
    parser.add_argument(
        "-p", "--port", required=True, help="Serial port to open (e.g., /dev/ttyUSB0 or COM3)"
    )
    parser.add_argument(
        "-b", "--baudrate", type=int, default=115200, help="Baudrate for the serial port (default: 115200)"
    )
    parser.add_argument("--init", type=str, default="2A0A0A", help="Initial message to send as hex string (e.g., '010203aabb')")

    args = parser.parse_args()

    dispatcher = SlipDispatcher()

    # Example handlers — you can register as needed
    # dispatcher.register_handler(0x01, handler1)
    # dispatcher.register_handler(0x01, handler2)
    # Start and get the protocol instance
    transport, _ = await dispatcher.start(args.port, baudrate=args.baudrate)

    if args.init:
        try:
            message = binascii.unhexlify(args.init)
            encoded = Slip.encode(message)
            transport.write(encoded)
            logger.debug(f"Sent initial hex message: {message.hex()}")
        except binascii.Error as e:
            logger.error(f"Invalid hex string in --init: {e}")
    
    # Keep running forever to receive incoming messages
    await asyncio.Event().wait()
            
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
