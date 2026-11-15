from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import aiohttp
from acidify_core.bot import Bot, IncomingMessage, SentMessage
from acidify_core.exceptions import MessageSendError, ServiceError, SignError
from acidify_core.messages import ForwardedNode, ParsedMessage, data_uri_to_bytes
from acidify_core.oidb import Friend, Group, GroupMember, UserInfo
from acidify_core.operations import (
    FriendRequest,
    GroupAnnouncement,
    GroupFileEntry,
    GroupFolderEntry,
    GroupNotification,
)
from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import MilkyConfig, RizifyConfig

MILKY_VERSION = "1.3"

API_PATHS = [
    "/get_login_info",
    "/get_impl_info",
    "/get_user_profile",
    "/get_friend_list",
    "/get_friend_info",
    "/get_group_list",
    "/get_group_info",
    "/get_group_member_list",
    "/get_group_member_info",
    "/get_peer_pins",
    "/set_peer_pin",
    "/set_avatar",
    "/set_nickname",
    "/set_bio",
    "/get_custom_face_url_list",
    "/get_cookies",
    "/get_csrf_token",
    "/send_private_message",
    "/send_group_message",
    "/recall_private_message",
    "/recall_group_message",
    "/get_message",
    "/get_history_messages",
    "/get_resource_temp_url",
    "/get_forwarded_messages",
    "/mark_message_as_read",
    "/send_friend_nudge",
    "/send_profile_like",
    "/delete_friend",
    "/get_friend_requests",
    "/accept_friend_request",
    "/reject_friend_request",
    "/set_group_name",
    "/set_group_avatar",
    "/set_group_member_card",
    "/set_group_member_special_title",
    "/set_group_member_admin",
    "/set_group_member_mute",
    "/set_group_whole_mute",
    "/kick_group_member",
    "/get_group_announcements",
    "/send_group_announcement",
    "/delete_group_announcement",
    "/get_group_essence_messages",
    "/set_group_essence_message",
    "/quit_group",
    "/send_group_message_reaction",
    "/send_group_nudge",
    "/get_group_notifications",
    "/accept_group_request",
    "/reject_group_request",
    "/accept_group_invitation",
    "/reject_group_invitation",
    "/upload_private_file",
    "/upload_group_file",
    "/get_private_file_download_url",
    "/get_group_file_download_url",
    "/get_group_files",
    "/move_group_file",
    "/rename_group_file",
    "/delete_group_file",
    "/persist_group_file",
    "/create_group_folder",
    "/rename_group_folder",
    "/delete_group_folder",
]


class ApiFailure(Exception):
    def __init__(self, retcode: int, message: str) -> None:
        super().__init__(message)
        self.retcode = retcode
        self.message = message


class SendPrivateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)
    message: list[dict[str, Any]]


class SendGroupInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    message: list[dict[str, Any]]


class PeerInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    no_cache: bool = False


class FriendInfoInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)
    no_cache: bool = False


class GroupInfoInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    no_cache: bool = False


class GroupMemberInfoInput(GroupInfoInput):
    user_id: int = Field(gt=0)


class UserProfileInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MessageSceneInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_scene: str
    peer_id: int = Field(gt=0)


class MessageSeqInput(MessageSceneInput):
    message_seq: int = Field(gt=0)


class HistoryInput(MessageSceneInput):
    start_message_seq: int | None = None
    limit: int = Field(default=20, ge=1, le=30)


class ResourceInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    resource_id: str = Field(min_length=1)


class ForwardInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    forward_id: str = Field(min_length=1)


class NudgeInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)
    is_self: bool = False


class PinInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_scene: str
    peer_id: int = Field(gt=0)
    is_pinned: bool = True


class ProfileLikeInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)
    count: int = Field(default=1, ge=1)


class DeleteFriendInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: int = Field(gt=0)


class FriendRequestsInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limit: int = Field(default=20, ge=1, le=100)
    is_filtered: bool = False


class FriendRequestActionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    initiator_uid: str = Field(min_length=1)
    is_filtered: bool = False


class SetNicknameInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    new_nickname: str


class SetBioInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    new_bio: str


class DomainInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    domain: str = Field(min_length=1)


class GroupRequestInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    notification_seq: int = Field(gt=0)
    notification_type: str
    is_filtered: bool = False
    reason: str | None = None


class GroupInvitationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    invitation_seq: int = Field(gt=0)


class SetGroupNameInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    new_group_name: str


class SetGroupMemberCardInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    card: str


class SetGroupMemberTitleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    special_title: str


class SetGroupMemberAdminInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    is_set: bool = True


class SetGroupMemberMuteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    duration: int = Field(default=0, ge=0)


class SetGroupWholeMuteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    is_mute: bool = True


class KickGroupMemberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    reject_add_request: bool = False


class AnnouncementInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    announcement_id: str = Field(min_length=1)


class SendAnnouncementInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    content: str
    image_uri: str | None = None


class EssenceListInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    page_index: int = Field(ge=0)
    page_size: int = Field(gt=0, le=100)


class SetEssenceInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    message_seq: int = Field(gt=0)
    is_set: bool = True


class GroupReactionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    message_seq: int = Field(gt=0)
    reaction: str = Field(min_length=1)
    reaction_type: str = "face"
    is_add: bool = True


class GroupNudgeInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)


class GroupNotificationsInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start_notification_seq: int | None = None
    is_filtered: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class GroupFileListInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    parent_folder_id: str = "/"


class GroupFileDownloadInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    file_id: str = Field(min_length=1)


class GroupFileMoveInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    file_id: str = Field(min_length=1)
    parent_folder_id: str = "/"
    target_folder_id: str = "/"


class GroupFileRenameInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    file_id: str = Field(min_length=1)
    parent_folder_id: str = "/"
    new_file_name: str = Field(min_length=1)


class GroupFileDeleteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    file_id: str = Field(min_length=1)


class GroupFolderCreateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    folder_name: str = Field(min_length=1)


class GroupFolderRenameInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    folder_id: str = Field(min_length=1)
    new_folder_name: str = Field(min_length=1)


class GroupFolderDeleteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    group_id: int = Field(gt=0)
    folder_id: str = Field(min_length=1)


class MilkyServer:
    def __init__(
        self,
        *,
        bot: Bot,
        config: RizifyConfig,
        version: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bot = bot
        self.config = config
        self.version = version
        self.logger = logger or logging.getLogger("rizify.milky.server")
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._webhook_tasks: list[asyncio.Task[None]] = []
        self._http: aiohttp.ClientSession | None = None
        self._self_info: UserInfo | None = None
        self._message_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._history: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._resource_urls: dict[str, str] = {}

    @property
    def milky_config(self) -> MilkyConfig:
        return self.config.milky

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[self._cors_middleware])
        prefix = self.milky_config.http.prefix
        for path in API_PATHS:
            app.router.add_post(prefix + path, self._api_handler)
        app.router.add_get("/event", self._event_handler)
        app.router.add_route("OPTIONS", "/{tail:.*}", self._options_handler)
        return app

    async def start(self) -> None:
        app = self.create_app()
        self._runner = web.AppRunner(app, access_log=logging.getLogger("aiohttp.access"))
        await self._runner.setup()
        http = self.milky_config.http
        self._site = web.TCPSite(self._runner, http.host, http.port)
        await self._site.start()
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5))
        self._event_task = asyncio.create_task(
            self._event_dispatch_loop(), name="rizify-event-dispatch"
        )
        for endpoint in self.milky_config.webhook_endpoints:
            self._webhook_tasks.append(
                asyncio.create_task(
                    self._webhook_loop(endpoint.url, endpoint.access_token),
                    name=f"rizify-webhook-{endpoint.url}",
                )
            )
        self.logger.info(
            "Rizify Milky 服务正在监听 http://%s:%s%s",
            http.host,
            http.port,
            http.prefix,
        )

    async def stop(self) -> None:
        for task in [self._event_task, *self._webhook_tasks]:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._event_task = None
        self._webhook_tasks.clear()
        if self._http is not None:
            await self._http.close()
            self._http = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        response: web.StreamResponse = await handler(request)
        origin = request.headers.get("Origin")
        allowed = self.config.security.cors_origins
        if origin and ("*" in allowed or origin in allowed):
            response.headers["Access-Control-Allow-Origin"] = "*" if "*" in allowed else origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Vary"] = "Origin"
        return response

    async def _options_handler(self, request: web.Request) -> web.Response:
        return web.Response(status=204)

    def _check_api_auth(self, request: web.Request) -> None:
        token = self.config.security.access_token
        if token and request.headers.get("Authorization") != f"Bearer {token}":
            raise web.HTTPUnauthorized()

    def _check_event_auth(self, request: web.Request) -> None:
        token = self.config.security.access_token
        if not token:
            return
        authorization = request.headers.get("Authorization")
        query_token = request.query.get("access_token")
        if authorization != f"Bearer {token}" and query_token != token:
            raise web.HTTPUnauthorized()

    async def _api_handler(self, request: web.Request) -> web.Response:
        self._check_api_auth(request)
        path = request.path
        prefix = self.milky_config.http.prefix
        if path.startswith(prefix):
            path = path[len(prefix) :]
        try:
            if not self.bot.is_online:
                raise ApiFailure(-403, "Bot is not logged in")
            try:
                payload = await request.json(loads=json.loads)
            except (json.JSONDecodeError, ValueError) as error:
                raise ApiFailure(-400, f"Bad request: {error}") from error
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                raise ApiFailure(-400, "Bad request: body must be a JSON object")
            data = await self._dispatch(path, payload)
            return web.json_response(
                {"status": "ok", "retcode": 0, "data": data},
                dumps=_json_dumps,
            )
        except ApiFailure as error:
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": error.retcode,
                    "message": error.message,
                },
                dumps=_json_dumps,
            )
        except ValidationError as error:
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": -400,
                    "message": f"Bad request: {error.errors()[0]['msg']}",
                },
                dumps=_json_dumps,
            )
        except ServiceError as error:
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": error.ret_code,
                    "message": str(error),
                },
                dumps=_json_dumps,
            )
        except SignError as error:
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": error.code,
                    "message": error.message,
                },
                dumps=_json_dumps,
            )
        except MessageSendError as error:
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": error.code,
                    "message": error.message,
                },
                dumps=_json_dumps,
            )
        except Exception as error:
            self.logger.exception("API %s 处理失败", path)
            return web.json_response(
                {
                    "status": "failed",
                    "retcode": -500,
                    "message": f"Internal error: {error}",
                },
                dumps=_json_dumps,
            )

    async def _dispatch(self, path: str, payload: dict[str, Any]) -> Any:
        if path == "/get_login_info":
            info = await self._get_self_info()
            return {"uin": self.bot.session.uin, "nickname": info.nickname}
        if path == "/get_impl_info":
            return {
                "impl_name": "Rizify",
                "impl_version": self.version,
                "qq_protocol_version": self.bot.app_info.current_version,
                "qq_protocol_type": self.bot.app_info.os,
                "milky_version": MILKY_VERSION,
            }
        if path == "/get_user_profile":
            profile_request = UserProfileInput.model_validate(payload)
            return _user_profile(await self.bot.fetch_user_info(profile_request.user_id))
        if path == "/get_friend_list":
            friend_list_request = PeerInput.model_validate(payload)
            if friend_list_request.no_cache or not self.bot._friends:
                friends = await self.bot.fetch_friends()
            else:
                friends = list(self.bot._friends.values())
            return {"friends": [_friend(friend) for friend in friends]}
        if path == "/get_friend_info":
            friend_request = FriendInfoInput.model_validate(payload)
            if friend_request.no_cache or friend_request.user_id not in self.bot._friends:
                await self.bot.fetch_friends()
            friend = self.bot._friends.get(friend_request.user_id)
            if friend is None:
                raise ApiFailure(-404, f"Friend {friend_request.user_id} not found")
            return {"friend": _friend(friend)}
        if path == "/get_group_list":
            group_list_request = PeerInput.model_validate(payload)
            if group_list_request.no_cache or not self.bot._groups:
                groups = await self.bot.fetch_groups()
            else:
                groups = list(self.bot._groups.values())
            return {"groups": [_group(group) for group in groups]}
        if path == "/get_group_info":
            group_request = GroupInfoInput.model_validate(payload)
            if group_request.no_cache or group_request.group_id not in self.bot._groups:
                await self.bot.fetch_groups()
            group = self.bot._groups.get(group_request.group_id)
            if group is None:
                raise ApiFailure(-404, f"Group {group_request.group_id} not found")
            return {"group": _group(group)}
        if path == "/get_group_member_list":
            member_list_request = GroupInfoInput.model_validate(payload)
            members = await self.bot.fetch_group_members(
                member_list_request.group_id,
                no_cache=member_list_request.no_cache,
            )
            return {
                "members": [_member(member_list_request.group_id, member) for member in members]
            }
        if path == "/get_group_member_info":
            member_request = GroupMemberInfoInput.model_validate(payload)
            members = await self.bot.fetch_group_members(
                member_request.group_id, no_cache=member_request.no_cache
            )
            member = next(
                (item for item in members if item.uin == member_request.user_id),
                None,
            )
            if member is None:
                raise ApiFailure(
                    -404,
                    f"Member {member_request.user_id} not found in group {member_request.group_id}",
                )
            return {"member": _member(member_request.group_id, member)}
        if path == "/send_private_message":
            private_request = SendPrivateInput.model_validate(payload)
            result = await self.bot.send_private_segments(
                private_request.user_id, private_request.message
            )
            return _sent(result)
        if path == "/send_group_message":
            group_message_request = SendGroupInput.model_validate(payload)
            await self._get_group(group_message_request.group_id)
            result = await self.bot.send_group_segments(
                group_message_request.group_id, group_message_request.message
            )
            return _sent(result)
        if path == "/recall_private_message":
            recall_request = MessageSeqInput.model_validate(payload)
            _require_scene(recall_request.message_scene)
            await self.bot.recall_message(
                scene=recall_request.message_scene,
                peer_id=recall_request.peer_id,
                sequence=recall_request.message_seq,
            )
            return {}
        if path == "/recall_group_message":
            recall_group_request = MessageSeqInput.model_validate(payload)
            _require_scene(recall_group_request.message_scene)
            await self.bot.recall_message(
                scene=recall_group_request.message_scene,
                peer_id=recall_group_request.peer_id,
                sequence=recall_group_request.message_seq,
            )
            return {}
        if path == "/get_message":
            get_request = MessageSeqInput.model_validate(payload)
            scene = _require_scene(get_request.message_scene)
            parsed = await self.bot.get_message(
                scene=scene,
                peer_id=get_request.peer_id,
                sequence=get_request.message_seq,
            )
            if parsed is None:
                raise ApiFailure(-404, "Message not found")
            return {"message": await self._message_from_parsed(parsed)}
        if path == "/get_history_messages":
            history_request = HistoryInput.model_validate(payload)
            scene = _require_scene(history_request.message_scene)
            history = await self.bot.get_history_messages(
                scene=scene,
                peer_id=history_request.peer_id,
                limit=history_request.limit,
                start_sequence=history_request.start_message_seq,
            )
            messages = [await self._message_from_parsed(message) for message in history.messages]
            return {
                "messages": messages,
                "next_message_seq": history.next_sequence,
            }
        if path == "/get_resource_temp_url":
            resource_request = ResourceInput.model_validate(payload)
            url = self._resource_urls.get(resource_request.resource_id)
            if not url and resource_request.resource_id.startswith(("http://", "https://")):
                url = resource_request.resource_id
            if not url:
                raise ApiFailure(
                    -404,
                    "该资源尚未出现在当前进程收到的消息中，无法解析临时链接",
                )
            return {"url": url}
        if path == "/get_forwarded_messages":
            forward_request = ForwardInput.model_validate(payload)
            nodes = await self.bot.get_forwarded_messages(forward_request.forward_id)
            return {
                "messages": [
                    _forwarded_message(node) for node in nodes if isinstance(node, ForwardedNode)
                ]
            }
        if path == "/mark_message_as_read":
            read_request = MessageSeqInput.model_validate(payload)
            scene = _require_scene(read_request.message_scene)
            timestamp = 0
            if scene == "friend":
                message = await self.bot.get_message(
                    scene=scene,
                    peer_id=read_request.peer_id,
                    sequence=read_request.message_seq,
                )
                if message is not None:
                    timestamp = message.timestamp
            await self.bot.mark_messages_as_read(
                scene=scene,
                peer_id=read_request.peer_id,
                sequence=read_request.message_seq,
                timestamp=timestamp,
            )
            return {}
        if path == "/send_friend_nudge":
            nudge_request = NudgeInput.model_validate(payload)
            await self.bot.send_friend_nudge(nudge_request.user_id, is_self=nudge_request.is_self)
            return {}
        if path == "/send_profile_like":
            like_request = ProfileLikeInput.model_validate(payload)
            await self.bot.send_profile_like(like_request.user_id, like_request.count)
            return {}
        if path == "/delete_friend":
            delete_request = DeleteFriendInput.model_validate(payload)
            await self.bot.delete_friend(delete_request.user_id)
            return {}
        if path == "/get_friend_requests":
            requests_request = FriendRequestsInput.model_validate(payload)
            requests = await self.bot.get_friend_requests(
                filtered=requests_request.is_filtered,
                limit=requests_request.limit,
            )
            return {"requests": [_friend_request(item) for item in requests]}
        if path in ("/accept_friend_request", "/reject_friend_request"):
            friend_action = FriendRequestActionInput.model_validate(payload)
            await self.bot.set_friend_request(
                initiator_uid=friend_action.initiator_uid,
                accept=path == "/accept_friend_request",
                filtered=friend_action.is_filtered,
            )
            return {}
        if path == "/get_peer_pins":
            pinned_friends, pinned_groups = await self.bot.get_pins()
            return {"friends": pinned_friends, "groups": pinned_groups}
        if path == "/set_peer_pin":
            pin_request = PinInput.model_validate(payload)
            if pin_request.message_scene == "friend":
                await self.bot.set_friend_pin(pin_request.peer_id, pin_request.is_pinned)
            elif pin_request.message_scene == "group":
                await self.bot.set_group_pin(pin_request.peer_id, pin_request.is_pinned)
            else:
                raise ApiFailure(-400, "message_scene 必须为 friend 或 group")
            return {}
        if path == "/set_nickname":
            nickname_request = SetNicknameInput.model_validate(payload)
            await self.bot.set_self_profile(nickname=nickname_request.new_nickname)
            self._self_info = None
            return {}
        if path == "/set_bio":
            bio_request = SetBioInput.model_validate(payload)
            await self.bot.set_self_profile(bio=bio_request.new_bio)
            self._self_info = None
            return {}
        if path == "/get_custom_face_url_list":
            EmptyInput.model_validate(payload)
            return {"urls": await self.bot.get_custom_face_urls()}
        if path == "/get_cookies":
            cookies_request = DomainInput.model_validate(payload)
            cookies = await self.bot.get_cookies(cookies_request.domain)
            return {"cookies": "; ".join(f"{key}={value}" for key, value in cookies.items())}
        if path == "/get_csrf_token":
            EmptyInput.model_validate(payload)
            return {"csrf_token": str(await self.bot.get_csrf_token())}
        if path == "/set_avatar":
            raise ApiFailure(
                -501,
                "Python 协议核心尚未移植头像 Highway 上传，不能设置账号头像",
            )
        if path == "/set_group_name":
            name_request = SetGroupNameInput.model_validate(payload)
            await self._get_group(name_request.group_id)
            await self.bot.set_group_name(name_request.group_id, name_request.new_group_name)
            return {}
        if path == "/set_group_avatar":
            raise ApiFailure(
                -501,
                "Python 协议核心尚未移植群头像上传，不能设置群头像",
            )
        if path == "/set_group_member_card":
            card_request = SetGroupMemberCardInput.model_validate(payload)
            await self._get_group(card_request.group_id)
            await self.bot.set_group_member_card(
                card_request.group_id, card_request.user_id, card_request.card
            )
            return {}
        if path == "/set_group_member_special_title":
            title_request = SetGroupMemberTitleInput.model_validate(payload)
            await self._get_group(title_request.group_id)
            await self.bot.set_group_member_title(
                title_request.group_id,
                title_request.user_id,
                title_request.special_title,
            )
            return {}
        if path == "/set_group_member_admin":
            admin_request = SetGroupMemberAdminInput.model_validate(payload)
            await self._get_group(admin_request.group_id)
            await self.bot.set_group_member_admin(
                admin_request.group_id,
                admin_request.user_id,
                admin_request.is_set,
            )
            return {}
        if path == "/set_group_member_mute":
            mute_request = SetGroupMemberMuteInput.model_validate(payload)
            await self._get_group(mute_request.group_id)
            await self.bot.set_group_member_mute(
                mute_request.group_id,
                mute_request.user_id,
                mute_request.duration,
            )
            return {}
        if path == "/set_group_whole_mute":
            whole_mute_request = SetGroupWholeMuteInput.model_validate(payload)
            await self._get_group(whole_mute_request.group_id)
            await self.bot.set_group_whole_mute(
                whole_mute_request.group_id, whole_mute_request.is_mute
            )
            return {}
        if path == "/kick_group_member":
            kick_request = KickGroupMemberInput.model_validate(payload)
            await self._get_group(kick_request.group_id)
            await self.bot.kick_group_member(
                kick_request.group_id,
                kick_request.user_id,
                reject_add_request=kick_request.reject_add_request,
            )
            return {}
        if path == "/get_group_announcements":
            group_request = GroupInfoInput.model_validate(payload)
            await self._get_group(group_request.group_id)
            announcements = await self.bot.get_group_announcements(group_request.group_id)
            return {"announcements": [_announcement(item) for item in announcements]}
        if path == "/send_group_announcement":
            announcement_request = SendAnnouncementInput.model_validate(payload)
            await self._get_group(announcement_request.group_id)
            image_bytes = None
            if announcement_request.image_uri is not None:
                try:
                    image_bytes = data_uri_to_bytes(announcement_request.image_uri)
                except (ValueError, TypeError) as exc:
                    raise ApiFailure(
                        -400,
                        "image_uri 必须为 base64:// 或 data: URI",
                    ) from exc
            announcement_id = await self.bot.send_group_announcement(
                announcement_request.group_id,
                announcement_request.content,
                image_bytes,
            )
            return {"announcement_id": announcement_id}
        if path == "/delete_group_announcement":
            delete_announcement = AnnouncementInput.model_validate(payload)
            await self._get_group(delete_announcement.group_id)
            await self.bot.delete_group_announcement(
                delete_announcement.group_id,
                delete_announcement.announcement_id,
            )
            return {}
        if path == "/get_group_essence_messages":
            essence_request = EssenceListInput.model_validate(payload)
            await self._get_group(essence_request.group_id)
            essence_result = await self.bot.get_group_essence_messages(
                essence_request.group_id,
                essence_request.page_index,
                essence_request.page_size,
            )
            return essence_result
        if path == "/set_group_essence_message":
            set_essence = SetEssenceInput.model_validate(payload)
            await self._get_group(set_essence.group_id)
            await self.bot.set_group_essence_message(
                set_essence.group_id,
                set_essence.message_seq,
                set_essence.is_set,
            )
            return {}
        if path == "/quit_group":
            quit_request = GroupInfoInput.model_validate(payload)
            await self._get_group(quit_request.group_id)
            await self.bot.quit_group(quit_request.group_id)
            return {}
        if path == "/send_group_message_reaction":
            reaction_request = GroupReactionInput.model_validate(payload)
            await self._get_group(reaction_request.group_id)
            reaction_type = {
                "face": 1,
                "emoji": 2,
            }.get(reaction_request.reaction_type)
            if reaction_type is None:
                raise ApiFailure(-400, "reaction_type 必须为 face 或 emoji")
            await self.bot.set_group_message_reaction(
                reaction_request.group_id,
                reaction_request.message_seq,
                reaction_request.reaction,
                reaction_type=reaction_type,
                is_add=reaction_request.is_add,
            )
            return {}
        if path == "/send_group_nudge":
            group_nudge = GroupNudgeInput.model_validate(payload)
            await self._get_group(group_nudge.group_id)
            await self.bot.send_group_nudge(group_nudge.group_id, group_nudge.user_id)
            return {}
        if path == "/get_group_notifications":
            notifications_request = GroupNotificationsInput.model_validate(payload)
            notifications, next_sequence = await self.bot.get_group_notifications(
                start_sequence=notifications_request.start_notification_seq,
                filtered=notifications_request.is_filtered,
                limit=notifications_request.limit,
            )
            return {
                "notifications": [_group_notification(item) for item in notifications],
                "next_notification_seq": next_sequence,
            }
        if path in ("/accept_group_request", "/reject_group_request"):
            group_action = GroupRequestInput.model_validate(payload)
            event_type = {
                "join_request": 1,
                "invited_join_request": 22,
            }.get(group_action.notification_type)
            if event_type is None:
                raise ApiFailure(
                    -400,
                    "notification_type 必须为 join_request 或 invited_join_request",
                )
            await self.bot.set_group_request(
                group_id=group_action.group_id,
                sequence=group_action.notification_seq,
                event_type=event_type,
                accept=path == "/accept_group_request",
                filtered=group_action.is_filtered,
                reason=group_action.reason or "",
            )
            return {}
        if path in ("/accept_group_invitation", "/reject_group_invitation"):
            invitation = GroupInvitationInput.model_validate(payload)
            await self.bot.set_group_invitation(
                group_id=invitation.group_id,
                invitation_seq=invitation.invitation_seq,
                accept=path == "/accept_group_invitation",
            )
            return {}
        if path == "/get_group_files":
            files_request = GroupFileListInput.model_validate(payload)
            await self._get_group(files_request.group_id)
            files_result = await self.bot.get_group_file_list(
                files_request.group_id, files_request.parent_folder_id
            )
            return {
                "files": [_group_file(files_request.group_id, item) for item in files_result.files],
                "folders": [
                    _group_folder(files_request.group_id, item) for item in files_result.folders
                ],
            }
        if path == "/get_group_file_download_url":
            download_request = GroupFileDownloadInput.model_validate(payload)
            await self._get_group(download_request.group_id)
            url = await self.bot.get_group_file_download_url(
                download_request.group_id, download_request.file_id
            )
            return {"download_url": url}
        if path == "/move_group_file":
            move_request = GroupFileMoveInput.model_validate(payload)
            await self._get_group(move_request.group_id)
            await self.bot.move_group_file(
                move_request.group_id,
                move_request.file_id,
                move_request.parent_folder_id,
                move_request.target_folder_id,
            )
            return {}
        if path == "/rename_group_file":
            rename_file = GroupFileRenameInput.model_validate(payload)
            await self._get_group(rename_file.group_id)
            await self.bot.rename_group_file(
                rename_file.group_id,
                rename_file.file_id,
                rename_file.parent_folder_id,
                rename_file.new_file_name,
            )
            return {}
        if path == "/delete_group_file":
            delete_file = GroupFileDeleteInput.model_validate(payload)
            await self._get_group(delete_file.group_id)
            await self.bot.delete_group_file(delete_file.group_id, delete_file.file_id)
            return {}
        if path == "/persist_group_file":
            persist_file = GroupFileDeleteInput.model_validate(payload)
            await self._get_group(persist_file.group_id)
            await self.bot.persist_group_file(persist_file.group_id, persist_file.file_id)
            return {}
        if path == "/create_group_folder":
            create_folder = GroupFolderCreateInput.model_validate(payload)
            await self._get_group(create_folder.group_id)
            folder_id = await self.bot.create_group_folder(
                create_folder.group_id, create_folder.folder_name
            )
            return {"folder_id": folder_id}
        if path == "/rename_group_folder":
            rename_folder = GroupFolderRenameInput.model_validate(payload)
            await self._get_group(rename_folder.group_id)
            await self.bot.rename_group_folder(
                rename_folder.group_id,
                rename_folder.folder_id,
                rename_folder.new_folder_name,
            )
            return {}
        if path == "/delete_group_folder":
            delete_folder = GroupFolderDeleteInput.model_validate(payload)
            await self._get_group(delete_folder.group_id)
            await self.bot.delete_group_folder(delete_folder.group_id, delete_folder.folder_id)
            return {}
        if path in (
            "/upload_private_file",
            "/upload_group_file",
            "/get_private_file_download_url",
        ):
            raise ApiFailure(
                -501,
                "Python 协议核心尚未移植私有文件/群文件 Highway 上传，"
                "当前仅支持已实现协议的群文件浏览与操作",
            )
        raise ApiFailure(
            -501,
            f"Milky 接口 {path} 已在 Python 服务中注册，但当前协议核心尚未提供该操作",
        )

    async def _get_group(self, group_id: int) -> Group:
        group = self.bot._groups.get(group_id)
        if group is None:
            await self.bot.fetch_groups()
            group = self.bot._groups.get(group_id)
        if group is None:
            raise ApiFailure(-404, f"Group {group_id} not found")
        return group

    async def _message_from_parsed(self, parsed: ParsedMessage) -> dict[str, Any]:
        friend: Friend | None = None
        group: Group | None = None
        member: GroupMember | None = None
        if parsed.scene == "friend":
            if parsed.peer_id not in self.bot._friends:
                with contextlib.suppress(Exception):
                    await self.bot.fetch_friends()
            friend = self.bot._friends.get(parsed.peer_id)
        else:
            group = self.bot._groups.get(parsed.peer_id)
            if group is None:
                with contextlib.suppress(Exception):
                    await self.bot.fetch_groups()
                group = self.bot._groups.get(parsed.peer_id)
            with contextlib.suppress(Exception):
                members = await self.bot.fetch_group_members(parsed.peer_id)
                member = next(
                    (item for item in members if item.uin == parsed.sender_id),
                    None,
                )
        incoming = IncomingMessage(
            message_scene=parsed.scene,
            peer_id=parsed.peer_id,
            message_seq=parsed.sequence,
            sender_id=parsed.sender_id,
            sender_uid=parsed.sender_uid,
            sender_name=parsed.sender_name,
            time=parsed.timestamp,
            random=parsed.random,
            segments=parsed.segments,
            friend=friend,
            group=group,
            group_member=member,
        )
        message = self.bot._message_to_milky(incoming)
        message["segments"] = _clean_segments(message.get("segments", []))
        self._remember_resources(message["segments"])
        self._message_cache[(parsed.scene, parsed.peer_id, parsed.sequence)] = message
        return message

    def _remember_resources(self, segments: Any) -> None:
        if not isinstance(segments, list):
            return
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            data = segment.get("data")
            if not isinstance(data, dict):
                continue
            resource_id = data.get("resource_id")
            temp_url = data.get("temp_url")
            if isinstance(resource_id, str) and isinstance(temp_url, str) and temp_url:
                self._resource_urls[resource_id] = temp_url
                self._resource_urls[temp_url] = temp_url
            nested = data.get("segments")
            if isinstance(nested, list):
                self._remember_resources(nested)

    async def _get_self_info(self) -> UserInfo:
        if self._self_info is None:
            try:
                self._self_info = await self.bot.fetch_user_info(self.bot.session.uin)
            except Exception:
                self._self_info = UserInfo(uin=self.bot.session.uin)
        return self._self_info

    async def _event_handler(self, request: web.Request) -> web.StreamResponse:
        self._check_event_auth(request)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._websocket_handler(request)
        return await self._sse_handler(request)

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        logger = logging.getLogger("rizify.milky.websocket")
        logger.info("WebSocket 事件流已连接")
        try:
            async with self.bot.subscribe() as queue:
                while not websocket.closed:
                    get_task = asyncio.create_task(queue.get())
                    close_task = asyncio.create_task(websocket.receive())
                    done, pending = await asyncio.wait(
                        {get_task, close_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if close_task in done:
                        message = close_task.result()
                        if message.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                    if get_task in done:
                        await websocket.send_str(_json_dumps(get_task.result()))
        finally:
            logger.info("WebSocket 事件流已断开")
        return websocket

    async def _sse_handler(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        await response.prepare(request)
        logging.getLogger("rizify.milky.sse").info("SSE 事件流已连接")
        try:
            async with self.bot.subscribe() as queue:
                while True:
                    event = await queue.get()
                    await response.write(
                        f"event: milky_event\ndata: {_json_dumps(event)}\n\n".encode()
                    )
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response

    async def _event_dispatch_loop(self) -> None:
        async with self.bot.subscribe() as queue:
            while True:
                event = await queue.get()
                data = event.get("data")
                if event.get("event_type") == "message_receive" and isinstance(data, dict):
                    scene = str(data.get("message_scene", ""))
                    peer_id = int(data.get("peer_id", 0))
                    sequence = int(data.get("message_seq", 0))
                    self._message_cache[(scene, peer_id, sequence)] = data
                    history = self._history.setdefault((scene, peer_id), [])
                    history.append(data)
                    if len(history) > 200:
                        del history[: len(history) - 200]
                    if len(self._message_cache) > 5000:
                        oldest = next(iter(self._message_cache))
                        self._message_cache.pop(oldest, None)

    async def _webhook_loop(self, url: str, token: str) -> None:
        logger = logging.getLogger("rizify.milky.webhook")
        semaphore = asyncio.Semaphore(16)
        client = self._http
        if client is None:
            return
        async with self.bot.subscribe() as queue:
            while True:
                event = await queue.get()
                await semaphore.acquire()

                async def send(item: dict[str, Any]) -> None:
                    try:
                        headers = {"Authorization": f"Bearer {token}"} if token else {}
                        async with client.post(url, json=item, headers=headers) as response:
                            await response.read()
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        logger.warning("发送事件到 Webhook %s 失败: %s", url, error)
                    finally:
                        semaphore.release()

                task = asyncio.create_task(send(event))
                self._webhook_tasks.append(task)
                task.add_done_callback(
                    lambda finished: (
                        self._webhook_tasks.remove(finished)
                        if finished in self._webhook_tasks
                        else None
                    )
                )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _friend(friend: Friend) -> dict[str, Any]:
    return {
        "user_id": friend.uin,
        "nickname": friend.nickname,
        "sex": _sex(friend.gender),
        "qid": friend.qid,
        "remark": friend.remark,
        "category": {
            "category_id": friend.category_id,
            "category_name": friend.category_name,
        },
    }


def _group(group: Group) -> dict[str, Any]:
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


def _member(group_id: int, member: GroupMember) -> dict[str, Any]:
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


def _user_profile(info: UserInfo) -> dict[str, Any]:
    return {
        "nickname": info.nickname,
        "qid": info.qid,
        "age": info.age,
        "sex": _sex(info.gender),
        "remark": info.remark,
        "bio": info.bio,
        "level": info.level,
        "country": info.country,
        "city": info.city,
        "school": info.school,
    }


def _sex(value: int) -> str:
    return {1: "male", 2: "female"}.get(value, "unknown")


def _sent(result: SentMessage) -> dict[str, Any]:
    return {"message_seq": result.message_seq, "time": result.time}


def _require_scene(value: str) -> str:
    if value not in ("friend", "group"):
        raise ApiFailure(-400, "message_scene 必须为 friend 或 group")
    return value


def _clean_segments(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_segments(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _clean_segments(item) for key, item in value.items() if not key.startswith("_")
        }
    return value


def _friend_request(request: FriendRequest) -> dict[str, Any]:
    return {
        "time": request.time,
        "initiator_id": request.initiator_uin,
        "initiator_uid": request.initiator_uid,
        "target_user_id": request.target_uin,
        "target_user_uid": request.target_uid,
        "state": request.state,
        "comment": request.comment,
        "via": request.via,
        "is_filtered": request.is_filtered,
    }


def _group_notification(notification: GroupNotification) -> dict[str, Any]:
    value: dict[str, Any] = {
        "notification_type": notification.notification_type,
        "group_id": notification.group_id,
        "notification_seq": notification.notification_seq,
        "is_filtered": notification.is_filtered,
        "state": notification.state,
        "operator_id": notification.operator_uin,
    }
    if notification.notification_type in (
        "join_request",
        "invited_join_request",
    ):
        value["initiator_id"] = notification.initiator_uin
        value["target_user_id"] = notification.target_uin
        value["comment"] = notification.comment
    elif notification.notification_type == "admin_change":
        value["target_user_id"] = notification.target_uin
        value["is_set"] = notification.is_set
    elif notification.notification_type in ("kick", "quit"):
        value["target_user_id"] = notification.target_uin
    return value


def _announcement(announcement: GroupAnnouncement) -> dict[str, Any]:
    return {
        "group_id": announcement.group_id,
        "announcement_id": announcement.announcement_id,
        "user_id": announcement.sender_id,
        "time": announcement.time,
        "content": announcement.content,
        "image_url": announcement.image_url,
    }


def _group_file(group_id: int, entry: GroupFileEntry) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "file_id": entry.file_id,
        "file_name": entry.file_name,
        "parent_folder_id": entry.parent_folder_id,
        "file_size": entry.file_size,
        "uploaded_time": entry.uploaded_time,
        "expire_time": entry.expire_time,
        "uploader_id": entry.uploader_uin,
        "downloaded_times": entry.downloaded_times,
    }


def _group_folder(group_id: int, entry: GroupFolderEntry) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "folder_id": entry.folder_id,
        "parent_folder_id": entry.parent_folder_id,
        "folder_name": entry.folder_name,
        "created_time": entry.create_time,
        "last_modified_time": entry.modified_time,
        "creator_id": entry.creator_uin,
        "file_count": entry.total_file_count,
    }


def _forwarded_message(node: ForwardedNode) -> dict[str, Any]:
    return {
        "message_seq": node.sequence,
        "sender_name": node.sender_name,
        "avatar_url": node.avatar_url,
        "time": node.timestamp,
        "segments": _clean_segments(node.segments),
    }
