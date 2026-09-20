# All rights reserved.
#
import asyncio
from typing import Union

from ntgcalls import TelegramServerError
from pyrogram.types import InlineKeyboardMarkup
from pytgcalls import PyTgCalls, filters
try:
    from pytgcalls.exceptions import AlreadyJoinedError, NoActiveGroupCall
except ImportError:
    from pytgcalls.exceptions import NoActiveGroupCall
    AlreadyJoinedError = NoActiveGroupCall
from pytgcalls.types import ChatUpdate, GroupCallConfig, MediaStream, Update
from pytgcalls.types import StreamEnded

import config
from strings import get_string
from VenomX import LOGGER, Platform, app, userbot
from VenomX.misc import db
from VenomX.utils.database import (
    add_active_chat, add_active_video_chat, get_audio_bitrate,
    get_instant_play, get_lang, get_loop, get_video_bitrate,
    group_assistant, music_on, remove_active_chat,
    remove_active_video_chat, set_loop,
)
from VenomX.utils.exceptions import AssistantErr
from VenomX.utils.inline.play import stream_markup, telegram_markup
from VenomX.utils.stream.autoclear import auto_clean
from VenomX.utils.thumbnails import gen_thumb

from pyrogram.errors import (
    ChannelsTooMuch, ChatAdminRequired, FloodWait,
    InviteRequestSent, UserAlreadyParticipant,
)
from VenomX.core.userbot import assistants
from VenomX.utils.database import get_assistant, set_assistant

links = {}

_PROXY = (getattr(config, "PROXY_URL", None) or "").strip()
_PROXY_FFMPEG = f"-http_proxy {_PROXY} " if _PROXY else ""
_REMOTE_FFMPEG_PARAMS = f"{_PROXY_FFMPEG}-analyzeduration 5000000 -probesize 131072 -thread_queue_size 4096 -fflags +genpts+discardcorrupt -flags low_delay"
_LOCAL_FFMPEG_PARAMS = "-thread_queue_size 4096 -analyzeduration 5000000 -probesize 131072 -fflags +genpts+discardcorrupt -flags low_delay"
_REMOTE_FFMPEG_PARAMS_VIDEO = f"{_PROXY_FFMPEG}-analyzeduration 3000000 -probesize 65536 -thread_queue_size 2048 -fflags +genpts+discardcorrupt+nobuffer -flags low_delay"
_LOCAL_FFMPEG_PARAMS_VIDEO = "-thread_queue_size 2048 -analyzeduration 3000000 -probesize 65536 -fflags +genpts+discardcorrupt+nobuffer -flags low_delay"


def _clear_(chat_id):
    async def _inner():
        popped = db.pop(chat_id, None)
        if popped:
            await auto_clean(popped)
        db[chat_id] = []
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        await set_loop(chat_id, 0)
    return _inner()


class Call:
    def __init__(self):
        self.calls = [PyTgCalls(client, cache_duration=100) for client in userbot.clients]
        self._recovering = set()

    async def pause_stream(self, chat_id):
        await (await group_assistant(self, chat_id)).pause_stream(chat_id)

    async def resume_stream(self, chat_id):
        await (await group_assistant(self, chat_id)).resume_stream(chat_id)

    async def mute_stream(self, chat_id):
        await (await group_assistant(self, chat_id)).mute_stream(chat_id)

    async def unmute_stream(self, chat_id):
        await (await group_assistant(self, chat_id)).unmute_stream(chat_id)

    async def stop_stream(self, chat_id):
        assistant = await group_assistant(self, chat_id)
        try:
            await _clear_(chat_id)
            await assistant.leave_call(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Failed to stop stream for chat {chat_id}: {e}")

    async def force_stop_stream(self, chat_id):
        assistant = await group_assistant(self, chat_id)
        try:
            check = db.get(chat_id)
            if check:
                check.pop(0)
        except Exception as e:
            LOGGER(__name__).error(f"Error popping queue for chat {chat_id}: {e}")
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        try:
            await assistant.leave_call(chat_id, close=False)
        except Exception as e:
            LOGGER(__name__).error(f"Failed to force leave call for chat {chat_id}: {e}")

    def _media_stream(self, link, video, audio_quality, video_quality, image=None):
        is_remote = isinstance(link, str) and link.startswith("http")
        ffmpeg_params = ((_REMOTE_FFMPEG_PARAMS_VIDEO if is_remote else _LOCAL_FFMPEG_PARAMS_VIDEO)
                         if video else (_REMOTE_FFMPEG_PARAMS if is_remote else _LOCAL_FFMPEG_PARAMS))
        if video:
            return MediaStream(link, audio_parameters=audio_quality, video_parameters=video_quality, ffmpeg_parameters=ffmpeg_params)
        if image and config.PRIVATE_BOT_MODE == str(True):
            return MediaStream(image, audio_path=link, audio_parameters=audio_quality, video_parameters=video_quality, ffmpeg_parameters=ffmpeg_params)
        return MediaStream(link, audio_parameters=audio_quality, video_flags=MediaStream.Flags.IGNORE, ffmpeg_parameters=ffmpeg_params)

    async def skip_stream(self, chat_id, link, video=None, image=None):
        assistant = await group_assistant(self, chat_id)
        stream = self._media_stream(link, video, await get_audio_bitrate(chat_id), await get_video_bitrate(chat_id), image)
        await assistant.play(chat_id, stream, config=GroupCallConfig(auto_start=False))

    async def seek_stream(self, chat_id, file_path, to_seek, duration, mode):
        assistant = await group_assistant(self, chat_id)
        audio_quality = await get_audio_bitrate(chat_id)
        video_quality = await get_video_bitrate(chat_id)
        remote = _PROXY_FFMPEG if isinstance(file_path, str) and file_path.startswith("http") else ""
        params = f"{remote}-ss {to_seek} -to {duration} -thread_queue_size {2048 if mode == 'video' else 4096} -analyzeduration 3000000 -probesize 65536 -fflags +genpts+discardcorrupt -flags low_delay"
        stream = MediaStream(file_path, audio_parameters=audio_quality, video_parameters=video_quality, ffmpeg_parameters=params) if mode == "video" else MediaStream(file_path, audio_parameters=audio_quality, ffmpeg_parameters=params, video_flags=MediaStream.Flags.IGNORE)
        await assistant.play(chat_id, stream, config=GroupCallConfig(auto_start=False))

    async def stream_call(self, link):
        assistant = await group_assistant(self, config.LOGGER_ID)
        join_as = getattr(assistant, "_cache_local_peer", None)
        if join_as is None:
            try:
                join_as = await assistant._app.resolve_peer(await assistant._app.get_id())
            except Exception as exc:
                LOGGER(__name__).warning(f"Could not resolve assistant peer for stream check: {type(exc).__name__}: {exc}")
        try:
            await assistant.play(config.LOGGER_ID, MediaStream(link), config=GroupCallConfig(auto_start=False, join_as=join_as))
            await asyncio.sleep(0.5)
            await assistant.leave_call(config.LOGGER_ID)
        except NoActiveGroupCall:
            raise
        except Exception as exc:
            LOGGER(__name__).warning(f"Stream sanity check failed: {type(exc).__name__}: {exc}")

    async def join_chat(self, chat_id, attempts=1):
        max_attempts = len(assistants) - 1
        assistant_client = await get_assistant(chat_id)
        try:
            _ = get_string(await get_lang(chat_id))
        except Exception:
            _ = get_string("en")
        try:
            chat = await app.get_chat(chat_id)
        except ChatAdminRequired:
            raise AssistantErr(_["call_1"])
        except Exception as e:
            raise AssistantErr(_["call_3"].format(app.mention, type(e).__name__))
        if chat_id in links:
            invitelink = links[chat_id]
        elif chat.username:
            invitelink = chat.username
            try: await assistant_client.resolve_peer(invitelink)
            except Exception: pass
            links[chat_id] = invitelink
        else:
            try: invitelink = await app.export_chat_invite_link(chat_id)
            except ChatAdminRequired: raise AssistantErr(_["call_1"])
            except Exception as e: raise AssistantErr(_["call_3"].format(app.mention, type(e).__name__))
            if invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace("https://t.me/+", "https://t.me/joinchat/")
            links[chat_id] = invitelink
        try:
            await asyncio.sleep(1)
            await assistant_client.join_chat(invitelink)
        except InviteRequestSent:
            try: await app.approve_chat_join_request(chat_id, assistant_client.id)
            except Exception as e: raise AssistantErr(_["call_3"].format(type(e).__name__))
            await asyncio.sleep(1)
            raise AssistantErr(_["call_6"].format(app.mention))
        except UserAlreadyParticipant: pass
        except ChannelsTooMuch:
            if attempts <= max_attempts:
                return await self.join_chat(chat_id, attempts + 1)
            raise AssistantErr(_["call_9"].format(config.SUPPORT_GROUP))
        except FloodWait as e:
            if e.value < 20:
                await asyncio.sleep(e.value)
                return await self.join_chat(chat_id, attempts + 1)
            if attempts <= max_attempts:
                return await self.join_chat(chat_id, attempts + 1)
            raise AssistantErr(_["call_10"].format(e.value))
        except Exception as e:
            raise AssistantErr(_["call_3"].format(type(e).__name__))

    async def join_call(self, chat_id, original_chat_id, link, video=None, image=None):
        assistant = await group_assistant(self, chat_id)
        stream = self._media_stream(link, video, await get_audio_bitrate(chat_id), await get_video_bitrate(chat_id), image)
        try:
            await assistant.play(chat_id=chat_id, stream=stream, config=GroupCallConfig(auto_start=False))
        except AlreadyJoinedError:
            # If the assistant is already connected, replace the media stream instead of
            # killing the call. This is important after Telegram reconnects.
            try:
                await assistant.play(chat_id=chat_id, stream=stream, config=GroupCallConfig(auto_start=False))
            except Exception as e:
                raise AssistantErr(f"**ASSISTANT PLAYBACK ERROR**\n\n{type(e).__name__}: {e}")
        except TelegramServerError:
            raise AssistantErr("**TELEGRAM SERVER ERROR**\n\nPlease restart the voice chat.")
        except Exception:
            await self.join_chat(chat_id)
            try:
                await assistant.play(chat_id=chat_id, stream=stream, config=GroupCallConfig(auto_start=False))
            except Exception as e:
                raise AssistantErr(f"**VOICE CHAT PLAYBACK ERROR**\n\n{type(e).__name__}: {e}")
        await add_active_chat(chat_id)
        await music_on(chat_id)
        if video:
            await add_active_video_chat(chat_id)

    async def _recover_after_left(self, client, chat_id):
        """Recover an unexpected assistant disconnect without clearing the queue."""
        if chat_id in self._recovering:
            return
        queue = db.get(chat_id) or []
        if not queue:
            return
        self._recovering.add(chat_id)
        try:
            LOGGER(__name__).warning(f"Assistant left active call {chat_id}; attempting playback recovery")
            await asyncio.sleep(1.5)
            current = db.get(chat_id) or []
            if not current:
                return
            item = current[0]
            await self.change_stream(client, chat_id, preserve_current=True)
        except Exception as exc:
            LOGGER(__name__).error(f"Assistant recovery failed for {chat_id}: {type(exc).__name__}: {exc}")
        finally:
            self._recovering.discard(chat_id)

    async def change_stream(self, client, chat_id, preserve_current=False):
        check = db.get(chat_id)
        if not check:
            await _clear_(chat_id)
            try: await client.leave_call(chat_id, close=False)
            except Exception: pass
            return
        popped = None
        loop = await get_loop(chat_id)
        if not preserve_current:
            try:
                if loop == 0:
                    popped = check.pop(0)
                else:
                    loop -= 1
                    await set_loop(chat_id, loop)
                if popped and popped.get("mystic"):
                    try: await popped["mystic"].delete()
                    except Exception: pass
                if popped:
                    await auto_clean(popped)
            except Exception as e:
                LOGGER(__name__).error(f"Error advancing queue for chat {chat_id}: {e}")
        if not check:
            await _clear_(chat_id)
            try: await client.leave_call(chat_id, close=False)
            except Exception: pass
            return

        queued = check[0]["file"]
        language = await get_lang(chat_id); _ = get_string(language)
        title = check[0]["title"].title(); user = check[0]["by"]; original_chat_id = check[0]["chat_id"]
        streamtype = check[0]["streamtype"]
        audio_quality = await get_audio_bitrate(chat_id); video_quality = await get_video_bitrate(chat_id)
        videoid = check[0]["vidid"]; check[0]["played"] = 0
        video = str(streamtype) == "video"
        call_config = GroupCallConfig(auto_start=False)

        try:
            if "vid_" in queued:
                n, stream_link = await Platform.youtube.stream_url(videoid, videoid=True, video=video)
                if n == 0:
                    stream_link, _direct = await Platform.youtube.download(videoid, None, videoid=True, video=video)
                stream = self._media_stream(stream_link, video, audio_quality, video_quality)
            elif "index_" in queued:
                stream = self._media_stream(videoid, video, audio_quality, video_quality)
            elif "live_" in queued:
                n, stream_link = await Platform.youtube.video(videoid, True)
                if n == 0:
                    raise RuntimeError("live stream URL unavailable")
                stream = self._media_stream(stream_link, video, audio_quality, video_quality)
            else:
                stream = self._media_stream(queued, video, audio_quality, video_quality)
            await client.play(chat_id, stream, config=call_config)
        except Exception as e:
            LOGGER(__name__).error(f"Unable to start queued media in {chat_id}: {type(e).__name__}: {e}")
            return await app.send_message(original_chat_id, text=_["call_7"])

        try:
            if "vid_" in queued:
                photo = await gen_thumb(videoid)
                button = stream_markup(_, videoid, chat_id)
                caption = _["stream_1"].format(title[:27], f"https://t.me/{app.username}?start=info_{videoid}", check[0]["dur"], user)
            else:
                photo = config.STREAM_IMG_URL
                button = telegram_markup(_, chat_id)
                caption = _["stream_2"].format(user)
            run = await app.send_photo(original_chat_id, photo=photo, caption=caption, reply_markup=InlineKeyboardMarkup(button))
            check[0]["mystic"] = run
            check[0]["markup"] = "stream"
        except Exception as e:
            LOGGER(__name__).warning(f"Playback notification failed: {e}")

    async def ping(self):
        return str(round(sum(c.ping for c in self.calls) / len(self.calls), 3)) if self.calls else "No active clients"

    async def start(self):
        LOGGER(__name__).info("Starting PyTgCall Clients")
        await asyncio.gather(*[c.start() for c in self.calls])
        await self.decorators()

    async def decorators(self):
        for call in self.calls:
            @call.on_update(filters.chat_update(ChatUpdate.Status.LEFT_CALL))
            async def stream_services_handler(client, update):
                # LEFT_CALL is not a user /stop command. Never clear the queue here.
                # An unexpected disconnect should recover the current track.
                try:
                    await self._recover_after_left(client, update.chat_id)
                except Exception as exc:
                    LOGGER(__name__).error(f"LEFT_CALL handler failed: {type(exc).__name__}: {exc}")

            @call.on_update(filters.stream_end())
            async def stream_end_handler(client, update: Update):
                try:
                    await self.change_stream(client, update.chat_id)
                except Exception as exc:
                    LOGGER(__name__).error(f"STREAM_END handler failed: {type(exc).__name__}: {exc}")

    def __getattr__(self, name):
        if not self.calls:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        first_call = self.calls[0]
        if hasattr(first_call, name):
            return getattr(first_call, name)
        raise AttributeError(f"'{type(first_call).__name__}' object has no attribute '{name}'")


Ayush = Call()
