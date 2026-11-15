from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from typing import Protocol

from .app_info import AppInfo
from .exceptions import ServiceError
from .packets import SsoResponse, decode_sso_packet, encode_sso_packet
from .session import SessionStore


class TransportClient(Protocol):
    app_info: AppInfo
    session: SessionStore
    logger: logging.Logger

    def next_sequence(self) -> int: ...


class PacketTransport:
    def __init__(
        self,
        client: TransportClient,
        host: str = "msfwifi.3g.qq.com",
        port: int = 8080,
    ) -> None:
        self.client = client
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[SsoResponse]] = {}
        self._push_queue: asyncio.Queue[SsoResponse] = asyncio.Queue(maxsize=256)
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._closed = False
        self._seen_sequences: set[int] = set()
        self._sequence_order: list[int] = []

    @property
    def push_queue(self) -> asyncio.Queue[SsoResponse]:
        return self._push_queue

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._writer is not None and not self._writer.is_closing():
                return
            self._closed = False
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=15
            )
            self._read_task = asyncio.create_task(self._read_loop(), name="rizify-packet-reader")

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                header = await self._reader.readexactly(4)
                packet_length = struct.unpack(">I", header)[0]
                if packet_length < 4 or packet_length > 64 * 1024 * 1024:
                    raise ValueError(f"无效的数据包长度: {packet_length}")
                body = await self._reader.readexactly(packet_length - 4)
                self.client.logger.debug("收到 SSO 帧，长度=%d", packet_length)
                response = decode_sso_packet(body, self.client.session.d2_key)
                future = self._pending.pop(response.sequence, None)
                if future is not None and not future.done():
                    future.set_result(response)
                    continue
                if self._is_duplicate(response.sequence):
                    continue
                try:
                    self._push_queue.put_nowait(response)
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._push_queue.get_nowait()
                    with contextlib.suppress(asyncio.QueueFull):
                        self._push_queue.put_nowait(response)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()
            if not self._closed:
                self.client.logger.warning("数据连接中断: %s", error)
            with contextlib.suppress(Exception):
                if self._writer is not None:
                    self._writer.close()
                    await self._writer.wait_closed()
            self._writer = None

    def _is_duplicate(self, sequence: int) -> bool:
        if sequence in self._seen_sequences:
            return True
        self._seen_sequences.add(sequence)
        self._sequence_order.append(sequence)
        if len(self._sequence_order) > 2048:
            old = self._sequence_order.pop(0)
            self._seen_sequences.discard(old)
        return False

    async def request(
        self,
        *,
        command: str,
        sequence: int,
        payload: bytes,
        request_type: str = "d2",
        encrypt_type: str = "d2",
        msg_type: int = 32,
        sign_result: object | None = None,
        timeout: float = 15,
    ) -> SsoResponse:
        await self.connect()
        assert self._writer is not None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SsoResponse] = loop.create_future()
        if sequence in self._pending:
            raise RuntimeError(f"重复的 SSO 序列号: {sequence}")
        self._pending[sequence] = future
        sign = getattr(sign_result, "sign", b"")
        token = getattr(sign_result, "token", b"")
        extra = getattr(sign_result, "extra", b"")
        packet = encode_sso_packet(
            app_info=self.client.app_info,
            session=self.client.session,
            command=command,
            sequence=sequence,
            payload=payload,
            request_type=request_type,
            encrypt_type=encrypt_type,
            msg_type=msg_type,
            sign=sign,
            token=token,
            extra=extra,
        )
        try:
            async with self._write_lock:
                self._writer.write(packet)
                await self._writer.drain()
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(sequence, None)
        if response.ret_code != 0:
            raise ServiceError(command, response.ret_code, response.extra)
        return response

    async def send_alive(self) -> None:
        await self.request(
            command="Heartbeat.Alive",
            sequence=self.client.next_sequence(),
            payload=bytes.fromhex("00000004"),
            request_type="simple",
            encrypt_type="none",
            timeout=10,
        )

    async def close(self) -> None:
        self._closed = True
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
        self._reader = None
