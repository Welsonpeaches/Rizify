from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .app_info import AppInfo
from .events import parse_push_events
from .exceptions import BotOnlineError, ServiceError, WtLoginError
from .messages import (
    HistoryResult,
    ParsedMessage,
    build_friend_history_request,
    build_group_history_request,
    build_outgoing_elems,
    build_peer_sequence_request,
    build_read_report,
    build_recall_friend,
    build_recall_group,
    build_receive_long_message,
    build_send_message,
    parse_common_message,
    parse_forwarded_nodes,
    parse_friend_history_response,
    parse_group_history_response,
    parse_peer_sequence_response,
    parse_received_long_messages,
    parse_send_message_response,
)
from .oidb import (
    Friend,
    Group,
    GroupMember,
    UserInfo,
    build_fetch_friends,
    build_fetch_group_members,
    build_fetch_groups,
    build_fetch_user_info_uid,
    build_fetch_user_info_uin,
    decode_oidb_envelope,
    parse_fetch_friends,
    parse_fetch_group_members,
    parse_fetch_groups,
    parse_user_info,
)
from .operations import (
    FriendRequest,
    GroupAnnouncement,
    GroupFileEntry,
    GroupFileList,
    GroupFolderEntry,
    GroupNotification,
    build_broadcast_group_file,
    build_custom_faces_request,
    build_delete_friend,
    build_essence_set,
    build_fetch_friend_requests,
    build_group_file_delete,
    build_group_file_download,
    build_group_file_folder_create,
    build_group_file_list,
    build_group_file_move,
    build_group_file_rename,
    build_group_folder_delete,
    build_group_folder_rename,
    build_group_notifications_request,
    build_group_reaction,
    build_kick_member,
    build_persist_group_file,
    build_poke,
    build_profile_like,
    build_profile_settings,
    build_pskey_request,
    build_quit_group,
    build_set_filtered_friend_request,
    build_set_friend_pin,
    build_set_group_name,
    build_set_group_pin,
    build_set_group_request,
    build_set_group_whole_mute,
    build_set_member_admin,
    build_set_member_card,
    build_set_member_mute,
    build_set_member_title,
    build_set_normal_friend_request,
    normalize_group_notification,
    parse_custom_faces,
    parse_friend_requests,
    parse_group_file_download,
    parse_group_file_list,
    parse_group_file_mutation,
    parse_group_folder_create,
    parse_group_folder_mutation,
    parse_group_notifications,
    parse_pinned_chats,
    parse_pskey_response,
)
from .packets import (
    QRCode,
    QRCodeState,
    SsoResponse,
    WtLoginCodec,
    build_bot_online_payload,
    build_fetch_qr_payload,
    build_pc_login_payload,
    build_query_qr_payload,
    parse_fetch_qr_payload,
    parse_pc_login_payload,
    parse_query_qr_payload,
    parse_register_response,
)
from .protobuf import field_message, field_varint, fields_map, get_bytes, get_varint
from .session import SessionStore
from .sign import SignProvider
from .transport import PacketTransport

QR_STATE_NAMES = {
    -1: "UNKNOWN",
    0: "CONFIRMED",
    17: "CODE_EXPIRED",
    48: "WAITING_FOR_SCAN",
    53: "WAITING_FOR_CONFIRMATION",
    54: "CANCELLED",
}


@dataclass(slots=True)
class SentMessage:
    message_seq: int
    time: int


@dataclass(slots=True)
class IncomingMessage:
    message_scene: str
    peer_id: int
    message_seq: int
    sender_id: int
    sender_uid: str
    sender_name: str
    time: int
    random: int
    segments: list[dict[str, Any]]
    friend: Friend | None = None
    group: Group | None = None
    group_member: GroupMember | None = None


def _strip_internal_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_internal_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_internal_fields(item)
            for key, item in value.items()
            if not key.startswith("_")
        }
    return value


class Bot:
    def __init__(
        self,
        *,
        uin: int,
        app_info: AppInfo,
        sign_provider: SignProvider,
        session: SessionStore | None = None,
        session_path: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if uin <= 0:
            raise ValueError("uin 必须大于 0")
        self.expected_uin = uin
        self.app_info = app_info
        self.sign_provider = sign_provider
        self.session = session or SessionStore(uin=uin)
        self.session_path = session_path
        self.logger = logger or logging.getLogger("rizify")
        self.transport = PacketTransport(self)
        self._sequence = random.randint(0x10000, 0x1FFFF)
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._push_task: asyncio.Task[None] | None = None
        self._closed = False
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._friends: dict[int, Friend] = {}
        self._groups: dict[int, Group] = {}
        self._group_members: dict[int, dict[int, GroupMember]] = {}
        self._group_locks: dict[int, asyncio.Lock] = {}
        self._uid_to_uin: dict[str, int] = {}
        self._uin_to_uid: dict[int, str] = {}
        self._user_info_cache: dict[int, UserInfo] = {}
        self._face_details: dict[str, dict[str, Any]] = {}
        self._skey = ""
        self._skey_expire_at = 0.0
        self._pskey_cache: dict[str, tuple[str, float]] = {}

    async def __aenter__(self) -> Bot:
        await self.transport.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    @property
    def is_online(self) -> bool:
        return self._heartbeat_task is not None and not self._heartbeat_task.done()

    @property
    def uin(self) -> int:
        return self.session.uin

    @property
    def uid(self) -> str:
        return self.session.uid

    def next_sequence(self) -> int:
        value = self._sequence
        self._sequence = (self._sequence + 1) & 0x7FFFFFFF
        if self._sequence == 0:
            self._sequence = 1
        return value

    async def _request(
        self,
        *,
        command: str,
        payload: bytes,
        encrypt_type: str = "d2",
        request_type: str = "d2",
        msg_type: int = 32,
        timeout: float = 15,
        sign: bool = True,
    ) -> SsoResponse:
        sequence = self.next_sequence()
        sign_result = None
        if sign:
            sign_result = await self.sign_provider.sign(command, sequence, payload)
        return await self.transport.request(
            command=command,
            sequence=sequence,
            payload=payload,
            request_type=request_type,
            encrypt_type=encrypt_type,
            msg_type=msg_type,
            sign_result=sign_result,
            timeout=timeout,
        )

    async def _wtlogin(
        self,
        *,
        command: str,
        sub_command: int,
        payload: bytes,
    ) -> bytes:
        codec = WtLoginCodec()
        wrapped = codec.wrap(self.app_info, self.session.uin, sub_command, payload)
        response = await self._request(
            command=command,
            payload=wrapped,
            encrypt_type="empty",
            request_type="d2",
            timeout=20,
        )
        return codec.unwrap(response.payload)

    async def fetch_qr_code(self, unusual_sig: bytes | None = None) -> QRCode:
        decrypted = await self._wtlogin(
            command="wtlogin.trans_emp",
            sub_command=2066,
            payload=build_fetch_qr_payload(self.app_info, self.session, unusual_sig),
        )
        qr_code = parse_fetch_qr_payload(decrypted)
        self.session.qr_sig = qr_code.qr_sig
        self.logger.info("二维码 URL：%s", qr_code.url)
        return qr_code

    async def query_qr_state(self) -> QRCodeState:
        decrypted = await self._wtlogin(
            command="wtlogin.trans_emp",
            sub_command=2066,
            payload=build_query_qr_payload(self.app_info, self.session),
        )
        return parse_query_qr_payload(decrypted)

    async def _get_face_uin(self, qr_string: str) -> int:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://ntlogin.qq.com/qr/getFace",
                    json={
                        "appid": self.app_info.app_id,
                        "faceUpdateTime": 0,
                        "qrsig": qr_string,
                    },
                )
                value = response.json()
                if isinstance(value, dict):
                    return int(value.get("uin", 0) or 0)
        except (httpx.HTTPError, ValueError):
            return 0
        return 0

    async def qr_login(
        self,
        *,
        qr_path: Path | None = None,
        query_interval: float = 3.0,
        on_qr: Any = None,
        on_state: Any = None,
    ) -> None:
        if query_interval < 1:
            raise ValueError("二维码查询间隔不能小于 1 秒")
        qr_code = await self.fetch_qr_code()
        if qr_path is not None:
            qr_path.parent.mkdir(parents=True, exist_ok=True)
            qr_path.write_bytes(qr_code.png)
            with contextlib.suppress(OSError):
                qr_path.chmod(0o600)
        if on_qr is not None:
            result = on_qr(qr_code)
            if asyncio.iscoroutine(result):
                await result
        self.logger.info("二维码已保存至 %s", qr_path or "(未保存)")
        while True:
            state = await self.query_qr_state()
            name = QR_STATE_NAMES.get(state.state, "UNKNOWN")
            self.logger.debug("二维码状态：%s (%s)", name, state.state)
            if on_state is not None:
                result = on_state(state)
                if asyncio.iscoroutine(result):
                    await result
            if state.state == 0:
                if state.uin != self.expected_uin:
                    raise WtLoginError(
                        -1,
                        "UinMismatch",
                        f"扫码账号 {state.uin} 与配置的 uin {self.expected_uin} 不一致",
                    )
                self.session.uin = state.uin
                self.session.tgtgt = state.tgtgt
                self.session.encrypted_a1 = state.encrypted_a1
                self.session.no_pic_sig = state.no_pic_sig
                self.logger.info("二维码已确认，登录用户：%s", state.uin)
                break
            if state.state == 17:
                raise TimeoutError("二维码已过期")
            if state.state == 54:
                raise RuntimeError("用户取消了登录")
            if state.state == 53:
                uin = await self._get_face_uin(qr_code.qr_string)
                if uin:
                    self.logger.info("二维码等待用户确认，登录用户：%s", uin)
            await asyncio.sleep(query_interval)
        decrypted = await self._wtlogin(
            command="wtlogin.login",
            sub_command=2064,
            payload=build_pc_login_payload(self.app_info, self.session),
        )
        tickets = parse_pc_login_payload(decrypted, self.session.tgtgt)
        self.session.uid = tickets.uid
        self.session.update_credentials(
            tickets.encrypted_a1,
            tickets.a2,
            tickets.d2,
            tickets.d2_key,
        )
        self.save_session()
        await self.online()

    async def login(self, *, qr_path: Path | None = None, query_interval: float = 3.0) -> None:
        if self.session.a2 and self.session.d2 and self.session.uid:
            try:
                await self.online()
                return
            except Exception as error:
                self.logger.warning("现有登录票据不可用，改用二维码登录: %s", error)
                self.session.clear()
        await self.qr_login(qr_path=qr_path, query_interval=query_interval)

    async def online(self) -> None:
        if not self.session.a2 or not self.session.d2:
            raise BotOnlineError("会话缺少登录票据，无法上线")
        await self.transport.connect()
        payload = build_bot_online_payload(self.app_info, self.session)
        response = await self._request(
            command="trpc.qq_new_tech.status_svc.StatusService.Register",
            payload=payload,
        )
        message = parse_register_response(response.payload)
        if message != "register success":
            raise BotOnlineError(message or "上线注册失败")
        if self._push_task is None or self._push_task.done():
            self._push_task = asyncio.create_task(self._push_loop(), name="rizify-push-loop")
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="rizify-heartbeat"
            )
        self.logger.info("已上线，协议版本 %s", self.app_info.current_version)

    async def _heartbeat_loop(self) -> None:
        count = 0
        try:
            while True:
                await self._request(
                    command="Heartbeat.Alive",
                    payload=bytes.fromhex("00000004"),
                    encrypt_type="none",
                    request_type="simple",
                    sign=False,
                    timeout=10,
                )
                count += 1
                if count % 27 == 0:
                    await self._request(
                        command="trpc.qq_new_tech.status_svc.StatusService.SsoHeartBeat",
                        payload=field_varint(1, 1),
                    )
                    count = 0
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.error("心跳失败，会话已离线: %s", error)
            await self._emit(
                {
                    "event_type": "bot_offline",
                    "time": int(time.time()),
                    "self_id": self.session.uin,
                    "data": {"reason": str(error)},
                }
            )

    async def _push_loop(self) -> None:
        while True:
            response = await self.transport.push_queue.get()
            if response.command != "trpc.msg.olpush.OlPushService.MsgPush":
                continue
            try:
                message = await self._parse_incoming(response.payload)
                events = await parse_push_events(
                    response.payload,
                    self.session.uin,
                    self.get_uin_by_uid,
                )
            except Exception as error:
                self.logger.debug("忽略无法解析的推送消息: %s", error)
                continue
            if message is not None:
                await self._emit(
                    {
                        "event_type": "message_receive",
                        "time": int(time.time()),
                        "self_id": self.session.uin,
                        "data": self._message_to_milky(message),
                    }
                )
            for event in events:
                await self._emit(event)

    async def _parse_incoming(self, payload: bytes) -> IncomingMessage | None:
        push = fields_map(payload)
        common_bytes = get_bytes(push, 1)
        common = fields_map(common_bytes)
        routing = fields_map(get_bytes(common, 1))
        content = fields_map(get_bytes(common, 2))
        content_type = get_varint(content, 1)
        if content_type not in (166, 82, 208, 529):
            return None
        group_fields = fields_map(get_bytes(routing, 8))
        group_id = get_varint(group_fields, 1)
        sender_uin = get_varint(routing, 1)
        sender_uid = get_bytes(routing, 2).decode(errors="replace")
        common_c2c = fields_map(get_bytes(routing, 7))
        sender_name = get_bytes(common_c2c, 6).decode(errors="replace")
        if group_id:
            sender_name = get_bytes(group_fields, 4).decode(errors="replace")
        parsed = parse_common_message(
            common_bytes,
            scene="group" if group_id else "friend",
            peer_id=group_id if group_id else sender_uin,
        )
        if not parsed.segments:
            return None
        if sender_uid:
            self._uid_to_uin[sender_uid] = sender_uin
            self._uin_to_uid[sender_uin] = sender_uid
        message = IncomingMessage(
            message_scene="group" if group_id else "friend",
            peer_id=group_id if group_id else sender_uin,
            message_seq=parsed.sequence,
            sender_id=sender_uin,
            sender_uid=sender_uid or parsed.sender_uid,
            sender_name=sender_name or parsed.sender_name,
            time=parsed.timestamp,
            random=parsed.random,
            segments=parsed.segments,
        )
        if group_id:
            if group_id not in self._groups:
                with contextlib.suppress(Exception):
                    await self.fetch_groups()
            message.group = self._groups.get(group_id)
            with contextlib.suppress(Exception):
                members = await self.fetch_group_members(group_id)
                message.group_member = next(
                    (member for member in members if member.uin == sender_uin), None
                )
        else:
            if sender_uin not in self._friends:
                with contextlib.suppress(Exception):
                    await self.fetch_friends()
            message.friend = self._friends.get(sender_uin)
        return message

    @staticmethod
    def _friend_to_milky(friend: Friend) -> dict[str, Any]:
        return {
            "user_id": friend.uin,
            "nickname": friend.nickname,
            "sex": _gender(friend.gender),
            "qid": friend.qid,
            "remark": friend.remark,
            "category": {
                "category_id": friend.category_id,
                "category_name": friend.category_name,
            },
        }

    @staticmethod
    def _group_to_milky(group: Group) -> dict[str, Any]:
        return {
            "group_id": group.uin,
            "group_name": group.name,
            "member_count": group.member_count,
            "max_member_count": group.capacity,
            "remark": group.remark,
            "created_time": group.created_at,
            "description": group.description,
            "question": group.question,
            "announcement": group.announcement_preview,
        }

    @staticmethod
    def _member_to_milky(group_id: int, member: GroupMember) -> dict[str, Any]:
        return {
            "user_id": member.uin,
            "nickname": member.nickname,
            "sex": "unknown",
            "group_id": group_id,
            "card": member.card,
            "title": member.special_title,
            "level": member.level,
            "role": member.role,
            "join_time": member.joined_at,
            "last_sent_time": member.last_spoke_at,
            "shut_up_end_time": member.muted_until,
        }

    def _message_to_milky(self, message: IncomingMessage) -> dict[str, Any]:
        value: dict[str, Any] = {
            "message_scene": message.message_scene,
            "peer_id": message.peer_id,
            "message_seq": message.message_seq,
            "sender_id": message.sender_id,
            "time": message.time,
            "segments": message.segments,
        }
        if message.message_scene == "friend":
            friend = message.friend or Friend(
                uin=message.sender_id,
                uid=message.sender_uid,
                nickname=message.sender_name,
            )
            value["friend"] = self._friend_to_milky(friend)
        else:
            group = message.group or Group(uin=message.peer_id)
            member = message.group_member or GroupMember(
                uin=message.sender_id,
                uid=message.sender_uid,
                nickname=message.sender_name,
            )
            value["group"] = self._group_to_milky(group)
            value["group_member"] = self._member_to_milky(message.peer_id, member)
        return value

    async def _emit(self, event: dict[str, Any]) -> None:
        event = _strip_internal_fields(event)
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async with self.subscribe() as queue:
            while True:
                yield await queue.get()

    async def _oidb(
        self, command: str, payload: bytes, *, reserved: bool = False, sign: bool = True
    ) -> bytes:
        if reserved:
            from .oidb import encode_oidb_envelope

            command_parts = command.removeprefix("OidbSvcTrpcTcp.").split("_")
            payload = encode_oidb_envelope(
                int(command_parts[0], 16),
                int(command_parts[1]),
                payload,
                reserved=True,
            )
        response = await self._request(command=command, payload=payload, sign=sign)
        return decode_oidb_envelope(response.payload)

    async def _oidb_body(
        self,
        command: str,
        body: bytes,
        *,
        reserved: bool = False,
        sign: bool = True,
    ) -> bytes:
        from .oidb import encode_oidb_envelope

        parts = command.removeprefix("OidbSvcTrpcTcp.").split("_")
        envelope = encode_oidb_envelope(int(parts[0], 16), int(parts[1]), body, reserved=reserved)
        return await self._oidb(command, envelope, sign=sign)

    async def _oidb_no_output(
        self,
        command: str,
        payload: bytes,
        *,
        reserved: bool = False,
    ) -> None:
        await self._oidb_body(command, payload, reserved=reserved)

    async def fetch_friends(self) -> list[Friend]:
        result: list[Friend] = []
        next_uin: int | None = None
        for _ in range(100):
            body = await self._oidb("OidbSvcTrpcTcp.0xfd4_1", build_fetch_friends(next_uin))
            batch, next_uin = parse_fetch_friends(body)
            result.extend(batch)
            if not next_uin:
                break
        self._friends = {friend.uin: friend for friend in result}
        for friend in result:
            if friend.uid:
                self._uid_to_uin[friend.uid] = friend.uin
                self._uin_to_uid[friend.uin] = friend.uid
        return result

    async def fetch_groups(self) -> list[Group]:
        body = await self._oidb("OidbSvcTrpcTcp.0xfe5_2", build_fetch_groups())
        groups = parse_fetch_groups(body)
        self._groups = {group.uin: group for group in groups}
        return groups

    async def fetch_group_members(
        self, group_id: int, *, no_cache: bool = False
    ) -> list[GroupMember]:
        lock = self._group_locks.setdefault(group_id, asyncio.Lock())
        async with lock:
            if not no_cache and group_id in self._group_members:
                return list(self._group_members[group_id].values())
            all_members: list[GroupMember] = []
            cookie: bytes | None = None
            for _ in range(100):
                body = await self._oidb(
                    "OidbSvcTrpcTcp.0xfe7_3",
                    build_fetch_group_members(group_id, cookie),
                )
                batch, cookie, _ = parse_fetch_group_members(body)
                all_members.extend(batch)
                if not cookie:
                    break
            self._group_members[group_id] = {member.uin: member for member in all_members}
            for member in all_members:
                if member.uid:
                    self._uid_to_uin[member.uid] = member.uin
                    self._uin_to_uid[member.uin] = member.uid
            return all_members

    async def fetch_user_info(self, uin: int) -> UserInfo:
        body = await self._oidb("OidbSvcTrpcTcp.0xfe1_2", build_fetch_user_info_uin(uin))
        info = parse_user_info(body)
        self._user_info_cache[uin] = info
        if info.uid:
            self._uid_to_uin[info.uid] = uin
            self._uin_to_uid[uin] = info.uid
        return info

    async def fetch_user_info_by_uid(self, uid: str) -> UserInfo:
        body = await self._oidb("OidbSvcTrpcTcp.0xfe1_2", build_fetch_user_info_uid(uid))
        info = parse_user_info(body)
        if not info.uid:
            info.uid = uid
        if info.uin:
            self._uid_to_uin[uid] = info.uin
            self._uin_to_uid[info.uin] = uid
            self._user_info_cache[info.uin] = info
        return info

    async def resolve_uid(self, uin: int, *, group_id: int | None = None) -> str:
        if uin == self.session.uin and self.session.uid:
            return self.session.uid
        cached = self._uin_to_uid.get(uin)
        if cached:
            return cached
        if group_id is not None:
            members = await self.fetch_group_members(group_id)
            for member in members:
                if member.uin == uin:
                    self._uin_to_uid[uin] = member.uid
                    self._uid_to_uin[member.uid] = uin
                    return member.uid
        if uin not in self._friends:
            with contextlib.suppress(Exception):
                await self.fetch_friends()
        friend = self._friends.get(uin)
        if friend is not None:
            self._uin_to_uid[uin] = friend.uid
            self._uid_to_uin[friend.uid] = uin
            return friend.uid
        info = await self.fetch_user_info(uin)
        if info.uid:
            self._uin_to_uid[uin] = info.uid
            self._uid_to_uin[info.uid] = uin
            return info.uid
        raise ValueError(f"无法解析用户 {uin} 的 uid")

    async def resolve_uin(self, uid: str) -> int:
        if uid == self.session.uid:
            return self.session.uin
        cached = self._uid_to_uin.get(uid)
        if cached:
            return cached
        info = await self.fetch_user_info_by_uid(uid)
        if info.uin:
            self._uid_to_uin[uid] = info.uin
            self._uin_to_uid[info.uin] = uid
        return info.uin

    async def get_uid_by_uin(
        self, uin: int, *, group_id: int | None = None, scene: str = "friend"
    ) -> str:
        return await self.resolve_uid(uin, group_id=group_id if scene == "group" else None)

    async def get_uin_by_uid(self, uid: str) -> int:
        return await self.resolve_uin(uid)

    async def get_display_name(
        self, uin: int, *, group_id: int | None = None, scene: str = "friend"
    ) -> str:
        if group_id is not None:
            members = await self.fetch_group_members(group_id)
            member = next((item for item in members if item.uin == uin), None)
            if member is not None:
                return member.card or member.nickname or str(uin)
        info = await self.fetch_user_info(uin)
        return info.nickname or str(uin)

    async def send_private_segments(
        self, user_id: int, segments: list[dict[str, Any]]
    ) -> SentMessage:
        friend = self._friends.get(user_id)
        if friend is None:
            await self.fetch_friends()
            friend = self._friends.get(user_id)
        if friend is None:
            raise ValueError(f"好友 {user_id} 不在好友列表中")
        elems = await build_outgoing_elems(
            self,
            scene="friend",
            peer_id=user_id,
            peer_uid=friend.uid,
            segments=segments,
        )
        sequence = random.getrandbits(63)
        random_id = random.randint(1, 0x7FFFFFFF)
        payload = build_send_message(
            scene="friend",
            peer_id=user_id,
            peer_uid=friend.uid,
            elems=elems,
            client_sequence=sequence,
            random=random_id,
        )
        response = await self._request(command="MessageSvc.PbSendMsg", payload=payload)
        result = parse_send_message_response(response.payload)
        if result[0] != 0:
            from .exceptions import MessageSendError

            raise MessageSendError(result[0], result[1])
        return SentMessage(result[2] or result[3], result[2])

    async def send_private_message(self, user_id: int, text: str) -> SentMessage:
        return await self.send_private_segments(user_id, [{"type": "text", "data": {"text": text}}])

    async def send_group_segments(
        self, group_id: int, segments: list[dict[str, Any]]
    ) -> SentMessage:
        elems = await build_outgoing_elems(
            self,
            scene="group",
            peer_id=group_id,
            peer_uid="",
            segments=segments,
        )
        sequence = random.getrandbits(63)
        random_id = random.randint(1, 0x7FFFFFFF)
        payload = build_send_message(
            scene="group",
            peer_id=group_id,
            peer_uid="",
            elems=elems,
            client_sequence=sequence,
            random=random_id,
        )
        response = await self._request(command="MessageSvc.PbSendMsg", payload=payload)
        result = parse_send_message_response(response.payload)
        if result[0] != 0:
            from .exceptions import MessageSendError

            raise MessageSendError(result[0], result[1])
        return SentMessage(result[2] or result[3], result[2])

    async def send_group_message(self, group_id: int, text: str) -> SentMessage:
        return await self.send_group_segments(group_id, [{"type": "text", "data": {"text": text}}])

    async def send_message(
        self,
        *,
        scene: str,
        peer_id: int,
        segments: list[dict[str, Any]],
    ) -> SentMessage:
        if scene == "friend":
            return await self.send_private_segments(peer_id, segments)
        if scene == "group":
            return await self.send_group_segments(peer_id, segments)
        raise ValueError(f"不支持的消息场景: {scene}")

    async def _friend_latest_sequence(self, friend_uid: str) -> int:
        response = await self._request(
            command="trpc.msg.msg_svc.MsgService.SsoGetPeerSeq",
            payload=build_peer_sequence_request(friend_uid),
        )
        return parse_peer_sequence_response(response.payload)

    async def _group_latest_sequence(self, group_id: int) -> int:
        body = field_varint(1, random.randint(1, 0x7FFFFFFF)) + field_message(
            2,
            field_varint(1, group_id) + field_message(2, field_varint(22, 1)),
        )
        response = await self._oidb_body("OidbSvcTrpcTcp.0x88d_0", body)
        info = fields_map(get_bytes(fields_map(response), 1))
        results = fields_map(get_bytes(info, 3))
        return get_varint(results, 22)

    async def get_history_messages(
        self,
        *,
        scene: str,
        peer_id: int,
        limit: int = 20,
        start_sequence: int | None = None,
    ) -> HistoryResult:
        if limit not in range(1, 31):
            raise ValueError("limit 必须在 1 到 30 之间")
        if scene == "friend":
            friend_uid = await self.resolve_uid(peer_id)
            end = (
                start_sequence
                if start_sequence is not None
                else await self._friend_latest_sequence(friend_uid)
            )
            start = max(1, end - limit + 1)
            response = await self._request(
                command="trpc.msg.register_proxy.RegisterProxy.SsoGetC2cMsg",
                payload=build_friend_history_request(friend_uid, start, end),
            )
            raws = parse_friend_history_response(response.payload)
        elif scene == "group":
            end = (
                start_sequence
                if start_sequence is not None
                else await self._group_latest_sequence(peer_id)
            )
            start = max(1, end - limit + 1)
            response = await self._request(
                command="trpc.msg.register_proxy.RegisterProxy.SsoGetGroupMsg",
                payload=build_group_history_request(peer_id, start, end),
            )
            raws = parse_group_history_response(response.payload)
        else:
            raise ValueError(f"不支持的消息场景: {scene}")
        messages: list[ParsedMessage] = []
        for raw in raws:
            try:
                messages.append(parse_common_message(raw, scene=scene, peer_id=peer_id))
            except Exception as error:
                self.logger.debug("忽略无法解析的历史消息: %s", error)
        messages.sort(key=lambda item: item.sequence)
        return HistoryResult(
            messages=messages,
            next_sequence=start - 1 if start > 1 else None,
        )

    async def get_message(self, *, scene: str, peer_id: int, sequence: int) -> ParsedMessage | None:
        history = await self.get_history_messages(
            scene=scene,
            peer_id=peer_id,
            limit=1,
            start_sequence=sequence,
        )
        return next(
            (item for item in history.messages if item.sequence == sequence),
            history.messages[0] if history.messages else None,
        )

    async def recall_message(self, *, scene: str, peer_id: int, sequence: int) -> None:
        if scene == "friend":
            target = await self.get_message(scene="friend", peer_id=peer_id, sequence=sequence)
            if target is None:
                raise ValueError(f"消息 {sequence} 不存在")
            target_uid = await self.resolve_uid(target.sender_id)
            payload = build_recall_friend(
                target_uid=target_uid,
                client_sequence=sequence,
                message_sequence=sequence,
                random=target.random,
                timestamp=target.timestamp,
            )
            await self._request(
                command="trpc.msg.msg_svc.MsgService.SsoC2CRecallMsg",
                payload=payload,
            )
        elif scene == "group":
            await self._request(
                command="trpc.msg.msg_svc.MsgService.SsoGroupRecallMsg",
                payload=build_recall_group(peer_id, sequence),
            )
        else:
            raise ValueError(f"不支持的消息场景: {scene}")

    async def mark_messages_as_read(
        self,
        *,
        scene: str,
        peer_id: int,
        sequence: int,
        timestamp: int = 0,
    ) -> None:
        if scene == "friend":
            target_uid = await self.resolve_uid(peer_id)
            payload = build_read_report(
                group_id=None,
                target_uid=target_uid,
                sequence=sequence,
                timestamp=timestamp,
            )
        elif scene == "group":
            payload = build_read_report(
                group_id=peer_id,
                target_uid=None,
                sequence=sequence,
                timestamp=0,
            )
        else:
            raise ValueError(f"不支持的消息场景: {scene}")
        await self._request(
            command="trpc.msg.msg_svc.MsgService.SsoReadedReport",
            payload=payload,
        )

    async def get_forwarded_messages(self, res_id: str) -> list[Any]:
        payload = build_receive_long_message(res_id, uid=self.session.uid, os_name=self.app_info.os)
        response = await self._request(
            command="trpc.msg.msg_svc.MsgService.SsoRecvLongMsg",
            payload=payload,
        )
        return parse_forwarded_nodes(parse_received_long_messages(response.payload))

    async def get_group_notifications(
        self,
        *,
        start_sequence: int | None = None,
        filtered: bool = False,
        limit: int = 20,
    ) -> tuple[list[GroupNotification], int | None]:
        if limit not in range(1, 101):
            raise ValueError("limit 必须在 1 到 100 之间")
        body = await self._oidb_body(
            f"OidbSvcTrpcTcp.0x10c0_{2 if filtered else 1}",
            build_group_notifications_request(start_sequence=start_sequence or 0, count=limit),
        )
        raw_items, next_sequence = parse_group_notifications(body, filtered=filtered)
        unresolved = {
            uid
            for item in raw_items
            for uid in (
                item["user1_uid"],
                item.get("user2_uid"),
                item.get("user3_uid"),
            )
            if uid and uid not in self._uid_to_uin
        }
        for uid in unresolved:
            with contextlib.suppress(Exception):
                await self.resolve_uin(uid)
        values = [
            value
            for item in raw_items
            if (value := normalize_group_notification(item, self._uid_to_uin)) is not None
        ]
        return values, next_sequence or None

    async def set_group_request(
        self,
        *,
        group_id: int,
        sequence: int,
        event_type: int,
        accept: bool,
        filtered: bool = False,
        reason: str = "",
    ) -> None:
        await self._oidb_no_output(
            f"OidbSvcTrpcTcp.0x10c8_{2 if filtered else 1}",
            build_set_group_request(
                group_id=group_id,
                sequence=sequence,
                event_type=event_type,
                accept=accept,
                reason=reason,
            ),
        )

    async def get_friend_requests(
        self, *, filtered: bool = False, limit: int = 20
    ) -> list[FriendRequest]:
        if limit not in range(1, 101):
            raise ValueError("limit 必须在 1 到 100 之间")
        command = "OidbSvcTrpcTcp.0xd69_0" if filtered else "OidbSvcTrpcTcp.0x5cf_11"
        body = await self._oidb_body(
            command,
            build_fetch_friend_requests(self_uid=self.session.uid, count=limit, filtered=filtered),
        )
        items = parse_friend_requests(body, filtered=filtered)
        values: list[FriendRequest] = []
        for item in items:
            source_uid = item["source_uid"]
            target_uid = self.session.uid if filtered else item.get("target_uid", "")
            initiator_uin = self._uid_to_uin.get(source_uid, 0)
            if not initiator_uin:
                with contextlib.suppress(Exception):
                    initiator_uin = await self.resolve_uin(source_uid)
            target_uin = self._uid_to_uin.get(target_uid, 0)
            if target_uid == self.session.uid:
                target_uin = self.session.uin
            elif not target_uin:
                with contextlib.suppress(Exception):
                    target_uin = await self.resolve_uin(target_uid)
            values.append(
                FriendRequest(
                    time=item["timestamp"],
                    initiator_uin=initiator_uin,
                    initiator_uid=source_uid,
                    target_uin=target_uin,
                    target_uid=target_uid,
                    state=item["state"],
                    comment=item["comment"],
                    via=item["via"],
                    is_filtered=filtered,
                )
            )
        return values

    async def set_friend_request(
        self, *, initiator_uid: str, accept: bool, filtered: bool = False
    ) -> None:
        if filtered:
            if not accept:
                raise ValueError("被过滤的好友请求只支持同意")
            await self._oidb_no_output(
                "OidbSvcTrpcTcp.0xd72_0",
                build_set_filtered_friend_request(self.session.uid, initiator_uid),
            )
            return
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0xb5d_44",
            build_set_normal_friend_request(initiator_uid, accept),
        )

    async def delete_friend(self, user_id: int, *, block: bool = False) -> None:
        uid = await self.resolve_uid(user_id)
        await self._oidb_no_output("OidbSvcTrpcTcp.0x126b_0", build_delete_friend(uid, block))
        self._friends.pop(user_id, None)

    async def send_profile_like(self, user_id: int, count: int = 1) -> None:
        uid = await self.resolve_uid(user_id)
        await self._oidb_no_output("OidbSvcTrpcTcp.0x7e5_104", build_profile_like(uid, count))

    async def send_friend_nudge(self, user_id: int, *, is_self: bool = False) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0xed3_1",
            build_poke(
                target_uin=self.session.uin if is_self else user_id,
                friend_uin=user_id,
            ),
        )

    async def send_group_nudge(self, group_id: int, user_id: int) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0xed3_1",
            build_poke(target_uin=user_id, group_id=group_id),
        )

    async def set_group_name(self, group_id: int, name: str) -> None:
        await self._oidb_no_output("OidbSvcTrpcTcp.0x89a_15", build_set_group_name(group_id, name))

    async def set_group_whole_mute(self, group_id: int, mute: bool) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x89a_0",
            build_set_group_whole_mute(group_id, mute),
        )

    async def set_group_member_card(self, group_id: int, user_id: int, card: str) -> None:
        uid = await self.get_uid_by_uin(user_id, group_id=group_id, scene="group")
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x8fc_3",
            build_set_member_card(group_id, uid, card),
        )
        with contextlib.suppress(Exception):
            members = await self.fetch_group_members(group_id, no_cache=True)
            member = next((item for item in members if item.uin == user_id), None)
            if member is not None:
                member.card = card

    async def set_group_member_title(self, group_id: int, user_id: int, title: str) -> None:
        if len(title.encode()) > 18:
            raise ValueError("专属头衔长度不能超过 18 个字节")
        uid = await self.get_uid_by_uin(user_id, group_id=group_id, scene="group")
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x8fc_2",
            build_set_member_title(group_id, uid, title),
        )

    async def set_group_member_admin(self, group_id: int, user_id: int, is_admin: bool) -> None:
        uid = await self.get_uid_by_uin(user_id, group_id=group_id, scene="group")
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x1096_1",
            build_set_member_admin(group_id, uid, is_admin),
        )

    async def set_group_member_mute(self, group_id: int, user_id: int, duration: int) -> None:
        if duration < 0:
            raise ValueError("禁言时长不能为负数")
        uid = await self.get_uid_by_uin(user_id, group_id=group_id, scene="group")
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x1253_1",
            build_set_member_mute(group_id, uid, duration),
        )

    async def kick_group_member(
        self,
        group_id: int,
        user_id: int,
        *,
        reject_add_request: bool = False,
        reason: str = "",
    ) -> None:
        uid = await self.get_uid_by_uin(user_id, group_id=group_id, scene="group")
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x8a0_1",
            build_kick_member(group_id, uid, reject_add_request, reason),
        )

    async def quit_group(self, group_id: int) -> None:
        await self._oidb_no_output("OidbSvcTrpcTcp.0x1097_1", build_quit_group(group_id))
        self._groups.pop(group_id, None)
        self._group_members.pop(group_id, None)

    async def set_group_essence_message(self, group_id: int, sequence: int, is_set: bool) -> None:
        target = await self.get_message(scene="group", peer_id=group_id, sequence=sequence)
        if target is None:
            raise ValueError(f"消息 {sequence} 不存在")
        await self._oidb_no_output(
            f"OidbSvcTrpcTcp.0xeac_{1 if is_set else 2}",
            build_essence_set(group_id, sequence, target.random),
        )

    async def set_group_message_reaction(
        self,
        group_id: int,
        sequence: int,
        code: str,
        *,
        reaction_type: int = 1,
        is_add: bool = True,
    ) -> None:
        await self._oidb_no_output(
            f"OidbSvcTrpcTcp.0x9082_{1 if is_add else 2}",
            build_group_reaction(group_id, sequence, code, reaction_type),
        )

    async def get_pins(self) -> tuple[list[int], list[int]]:
        body = await self._oidb_body("OidbSvcTrpcTcp.0x12b3_0", b"")
        parsed_friend_uids, group_uins = parse_pinned_chats(body)
        friend_uins: list[int] = []
        for uid in parsed_friend_uids:
            with contextlib.suppress(Exception):
                friend_uins.append(await self.get_uin_by_uid(uid))
        return friend_uins, group_uins

    async def set_friend_pin(self, user_id: int, is_pinned: bool) -> None:
        uid = await self.get_uid_by_uin(user_id)
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x5d6_18",
            build_set_friend_pin(uid, is_pinned, int(time.time())),
        )

    async def set_group_pin(self, group_id: int, is_pinned: bool) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x5d6_1",
            build_set_group_pin(group_id, is_pinned, int(time.time())),
        )

    async def get_custom_face_urls(self) -> list[str]:
        response = await self._request(
            command="Faceroam.OpReq",
            payload=build_custom_faces_request(self.uin),
        )
        return parse_custom_faces(response.payload, self.uin)

    async def _get_client_key(self) -> str:
        body = await self._oidb_body("OidbSvcTrpcTcp.0x102a_1", b"")
        key = get_bytes(fields_map(body), 3).decode("utf-8", errors="replace")
        if not key:
            raise ServiceError("FetchClientKey", 0, "响应中没有 clientKey")
        return key

    async def get_skey(self) -> str:
        if self._skey and time.time() < self._skey_expire_at:
            return self._skey
        client_key = await self._get_client_key()
        jump = (
            "https%3A%2F%2Fh5.qzone.qq.com%2Fqqnt%2Fqzoneinpcqq%2Ffriend"
            "%3Frefresh%3D0%26clientuin%3D0%26darkMode%3D0"
            "&keyindex=19&random=2599"
        )
        url = (
            "https://ssl.ptlogin2.qq.com/jump"
            "?ptlang=1033"
            f"&clientuin={self.uin}"
            f"&clientkey={client_key}"
            f"&u1={jump}"
        )
        async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
            response = await client.get(url)
            skey = client.cookies.get("skey") or response.cookies.get("skey")
        if not skey:
            raise ServiceError("GetSKey", response.status_code, "跳转响应中没有 skey")
        self._skey = skey
        self._skey_expire_at = time.time() + 86400
        return skey

    async def get_csrf_token(self) -> int:
        skey = await self.get_skey()
        value = 5381
        for byte in skey.encode("utf-8"):
            value += (value << 5) + byte
        return value & 0x7FFFFFFF

    async def get_pskey(self, domain: str) -> str:
        cached = self._pskey_cache.get(domain)
        if cached is not None and time.time() < cached[1]:
            return cached[0]
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x102a_0",
            build_pskey_request([domain]),
        )
        values = parse_pskey_response(body)
        key = values.get(domain, "")
        if not key:
            raise ServiceError("FetchPSKey", 0, f"没有 {domain} 的 p_skey")
        self._pskey_cache[domain] = (key, time.time() + 86400)
        return key

    async def get_cookies(self, domain: str) -> dict[str, str]:
        return {
            "p_uin": f"o{self.uin}",
            "p_skey": await self.get_pskey(domain),
            "skey": await self.get_skey(),
            "uin": str(self.uin),
        }

    async def _web_request(
        self,
        method: str,
        url: str,
        domain: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        cookies = await self.get_cookies(domain)
        request_params = dict(params or {})
        request_params["bkn"] = str(await self.get_csrf_token())
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                params=request_params,
                data=data,
                files=files,
                cookies=cookies,
                headers={
                    "User-Agent": ("Dalvik/2.1.0 (Linux; U; Android 7.1.2; PCRT00 Build/N2G48H)")
                },
            )
        if response.status_code >= 400:
            raise ServiceError("WebApi", response.status_code, url)
        return response

    async def get_group_announcements(self, group_id: int) -> list[GroupAnnouncement]:
        response = await self._web_request(
            "GET",
            "https://web.qun.qq.com/cgi-bin/announce/get_t_list",
            "qun.qq.com",
            params={
                "qid": group_id,
                "ft": 23,
                "ni": 1,
                "n": 20,
                "i": 1,
                "log_read": 1,
                "platform": 1,
                "s": -1,
            },
        )
        payload = response.json()
        feeds = payload.get("feeds", []) + payload.get("inst", [])
        result: list[GroupAnnouncement] = []
        for feed in feeds:
            message = feed.get("msg", {})
            images = message.get("pics", [])
            settings = feed.get("settings", {})
            result.append(
                GroupAnnouncement(
                    group_id=group_id,
                    announcement_id=str(feed.get("fid", "")),
                    sender_id=int(feed.get("u", 0) or 0),
                    time=int(feed.get("pubt", 0) or 0),
                    content=html.unescape(str(message.get("text", ""))),
                    image_url=(
                        f"https://gdynamic.qpic.cn/gdynamic/{images[0].get('id', '')}/0"
                        if images
                        else None
                    ),
                    show_edit_card=settings.get("is_show_edit_card", 0) == 1,
                    show_tip_window=settings.get("tip_window_type", 0) == 1,
                    confirm_required=settings.get("confirm_required", 0) == 1,
                    is_pinned=feed.get("pinned", 0) == 1,
                    show_to_new_member=feed.get("type", 0) == 20,
                )
            )
        return result

    async def send_group_announcement(
        self,
        group_id: int,
        content: str,
        image: bytes | None = None,
        *,
        show_edit_card: bool = False,
        show_tip_window: bool = True,
        confirm_required: bool = True,
        is_pinned: bool = False,
    ) -> str:
        image_info: dict[str, Any] | None = None
        if image is not None:
            if image.startswith(b"\x89PNG\r\n\x1a\n"):
                extension, content_type = "png", "image/png"
            elif image.startswith((b"GIF87a", b"GIF89a")):
                extension, content_type = "gif", "image/gif"
            elif image.startswith(b"\xff\xd8\xff"):
                extension, content_type = "jpg", "image/jpeg"
            else:
                extension, content_type = "bin", "application/octet-stream"
            upload = await self._web_request(
                "POST",
                "https://web.qun.qq.com/cgi-bin/announce/upload_img",
                "qun.qq.com",
                data={
                    "bkn": str(await self.get_csrf_token()),
                    "source": "troopNotice",
                    "m": "0",
                },
                files={
                    "pic_up": (
                        f"group-announcement.{extension}",
                        image,
                        content_type,
                    )
                },
            )
            upload_payload = upload.json()
            if int(upload_payload.get("ec", -1)) != 0:
                raise ServiceError(
                    "UploadAnnouncementImage",
                    int(upload_payload.get("ec", -1)),
                    str(upload_payload.get("em", "")),
                )
            image_info = json.loads(html.unescape(str(upload_payload.get("id", "{}"))))
        form: dict[str, Any] = {
            "qid": str(group_id),
            "bkn": str(await self.get_csrf_token()),
            "text": content,
            "pinned": "1" if is_pinned else "0",
            "type": "1",
            "settings": json.dumps(
                {
                    "is_show_edit_card": 1 if show_edit_card else 0,
                    "tip_window_type": 1 if show_tip_window else 0,
                    "confirm_required": 1 if confirm_required else 0,
                },
                separators=(",", ":"),
            ),
        }
        if image_info is not None:
            form["pic"] = image_info.get("id", "")
            form["imgWidth"] = image_info.get("w", "")
            form["imgHeight"] = image_info.get("h", "")
        response = await self._web_request(
            "POST",
            "https://web.qun.qq.com/cgi-bin/announce/add_qun_notice",
            "qun.qq.com",
            data=form,
        )
        payload = response.json()
        announcement_id = str(payload.get("new_fid", ""))
        if not announcement_id:
            raise ServiceError("SendAnnouncement", 0, "响应中没有 new_fid")
        return announcement_id

    async def delete_group_announcement(self, group_id: int, announcement_id: str) -> None:
        await self._web_request(
            "GET",
            "https://web.qun.qq.com/cgi-bin/announce/del_feed",
            "qun.qq.com",
            params={
                "fid": announcement_id,
                "qid": group_id,
                "ft": 23,
                "op": 1,
            },
        )

    async def get_group_essence_messages(
        self, group_id: int, page_index: int, page_size: int
    ) -> dict[str, Any]:
        response = await self._web_request(
            "GET",
            "https://qun.qq.com/cgi-bin/group_digest/digest_list",
            "qun.qq.com",
            params={
                "random": 7800,
                "X-CROSS-ORIGIN": "fetch",
                "group_code": group_id,
                "page_start": page_index,
                "page_limit": page_size,
            },
        )
        payload = response.json()
        data = payload.get("data", {})
        messages: list[dict[str, Any]] = []
        for item in data.get("msg_list") or []:
            segments: list[dict[str, Any]] = []
            for element in item.get("msg_content", []):
                message_type = element.get("msg_type")
                if message_type == 1:
                    segments.append(
                        {
                            "type": "text",
                            "data": {"text": str(element.get("text", ""))},
                        }
                    )
                elif message_type == 2:
                    segments.append(
                        {
                            "type": "face",
                            "data": {"face_id": str(element.get("face_index", 0))},
                        }
                    )
                elif message_type == 3:
                    segments.append(
                        {
                            "type": "image",
                            "data": {"url": str(element.get("image_url", ""))},
                        }
                    )
                elif message_type == 4:
                    segments.append(
                        {
                            "type": "video",
                            "data": {"url": str(element.get("file_thumbnail_url", ""))},
                        }
                    )
            if not segments:
                continue
            messages.append(
                {
                    "group_id": group_id,
                    "message_seq": int(item.get("msg_seq", 0) or 0),
                    "message_time": int(item.get("sender_time", 0) or 0),
                    "sender_id": int(item.get("sender_uin", 0) or 0),
                    "sender_name": str(item.get("sender_nick", "")),
                    "operator_id": int(item.get("add_digest_uin", 0) or 0),
                    "operator_name": str(item.get("add_digest_nick", "")),
                    "operation_time": int(item.get("add_digest_time", 0) or 0),
                    "segments": segments,
                }
            )
        return {"messages": messages, "is_end": bool(data.get("is_end", False))}

    async def set_group_invitation(self, group_id: int, invitation_seq: int, accept: bool) -> None:
        await self.set_group_request(
            group_id=group_id,
            sequence=invitation_seq,
            event_type=2,
            accept=accept,
            filtered=False,
        )

    async def get_group_file_list(
        self, group_id: int, directory: str = "/", start_index: int = 0
    ) -> GroupFileList:
        files: list[GroupFileEntry] = []
        folders: list[GroupFolderEntry] = []
        index = start_index
        while True:
            body = await self._oidb_body(
                "OidbSvcTrpcTcp.0x6d8_1",
                build_group_file_list(group_id, directory, index, 100),
                reserved=True,
            )
            batch_files, batch_folders, is_end = parse_group_file_list(body)
            files.extend(batch_files)
            folders.extend(batch_folders)
            if is_end:
                break
            index += 100
        return GroupFileList(files=files, folders=folders)

    async def get_group_file_download_url(self, group_id: int, file_id: str) -> str:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d6_2",
            build_group_file_download(group_id, file_id),
            reserved=True,
        )
        return parse_group_file_download(body)

    async def delete_group_file(self, group_id: int, file_id: str) -> None:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d6_3",
            build_group_file_delete(group_id, file_id),
            reserved=True,
        )
        parse_group_file_mutation(body, 4)

    async def rename_group_file(
        self,
        group_id: int,
        file_id: str,
        parent_folder_id: str,
        new_name: str,
    ) -> None:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d6_4",
            build_group_file_rename(group_id, file_id, parent_folder_id, new_name),
            reserved=True,
        )
        parse_group_file_mutation(body, 5)

    async def move_group_file(
        self,
        group_id: int,
        file_id: str,
        parent_folder_id: str,
        target_folder_id: str,
    ) -> None:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d6_5",
            build_group_file_move(group_id, file_id, parent_folder_id, target_folder_id),
            reserved=True,
        )
        parse_group_file_mutation(body, 6)

    async def persist_group_file(self, group_id: int, file_id: str) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x6d9_0",
            build_persist_group_file(group_id, file_id),
            reserved=True,
        )

    async def create_group_folder(self, group_id: int, name: str) -> str:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d7_0",
            build_group_file_folder_create(group_id, name),
            reserved=True,
        )
        return parse_group_folder_create(body)

    async def delete_group_folder(self, group_id: int, folder_id: str) -> None:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d7_1",
            build_group_folder_delete(group_id, folder_id),
            reserved=True,
        )
        parse_group_folder_mutation(body, 2)

    async def rename_group_folder(self, group_id: int, folder_id: str, name: str) -> None:
        body = await self._oidb_body(
            "OidbSvcTrpcTcp.0x6d7_2",
            build_group_folder_rename(group_id, folder_id, name),
            reserved=True,
        )
        parse_group_folder_mutation(body, 3)

    async def broadcast_group_file(self, group_id: int, file_id: str) -> None:
        await self._oidb_no_output(
            "OidbSvcTrpcTcp.0x6d9_4",
            build_broadcast_group_file(group_id, file_id, random.randint(0, 0x7FFFFFFF)),
        )

    async def set_self_profile(
        self, *, nickname: str | None = None, bio: str | None = None
    ) -> None:
        if nickname is None and bio is None:
            raise ValueError("至少需要修改昵称或个性签名")
        body = field_varint(1, self.session.uin) + build_profile_settings(
            nickname=nickname, bio=bio
        )
        await self._oidb_no_output("OidbSvcTrpcTcp.0x112a_2", body)

    def save_session(self) -> None:
        if self.session_path is not None:
            self.session.save(self.session_path)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in (self._heartbeat_task, self._push_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._heartbeat_task = None
        self._push_task = None
        await self.transport.close()
        if hasattr(self.sign_provider, "close"):
            await self.sign_provider.close()


def _gender(value: int) -> str:
    return {1: "male", 2: "female"}.get(value, "unknown")
