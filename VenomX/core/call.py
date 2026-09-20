# All rights reserved.

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
from pytgcalls.types import (
    ChatUpdate,
    GroupCallConfig,
    MediaStream,
    Update,
)
from pytgcalls.types import StreamEnded

import config
from strings import get_string
from VenomX import LOGGER, Platform, app, userbot
from VenomX.misc import db
from VenomX.utils.database import (
    add_active_chat,
    add_active_video_chat,
    get_audio_bitrate,
    get_instant_play,
    get_lang,
    get_loop,
    get_video_bitrate,
    group_assistant,
    music_on,
    remove_active_chat,
    remove_active_video_chat,
    set_loop,
)
from VenomX.utils.exceptions import AssistantErr
from VenomX.utils.inline.play import stream_markup, telegram_markup
from VenomX.utils.stream.autoclear import auto_clean
from VenomX.utils.thumbnails import gen_thumb

from pyrogram.errors import (
    ChannelsTooMuch,
    ChatAdminRequired,
    FloodWait,
    InviteRequestSent,
    UserAlreadyParticipant,
)

from VenomX.core.userbot import assistants
from VenomX.utils.database import (
    get_assistant,
    get_lang,
    set_assistant,
)

links = {}

# YouTube videoplayback URLs are signed and can be bound to the network path
# that created them. When a proxy is configured, FFmpeg MUST use that same
# proxy. Do not rotate the proxy while a track is playing.
_PROXY = (getattr(config, "PROXY_URL", None) or "").strip()
_PROXY_FFMPEG = f"-http_proxy {_PROXY} " if _PROXY else ""

# Reconnect is safe for direct connections and improves resilience to short
# network interruptions. FFmpeg reconnect options are intentionally disabled
# when a proxy is configured because some HTTP proxies mishandle them.
_RECONNECT_FFMPEG = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 "
    "-reconnect_delay_max 5 "
    if not _PROXY
    else ""
)

# INPUT-side parameters only. PyTgCalls places these before the media input.
# Encoding/output parameters must NOT be placed here.
_REMOTE_FFMPEG_PARAMS = (
    f"{_PROXY_FFMPEG}"
    f"{_RECONNECT_FFMPEG}"
    "-rw_timeout 15000000 "
    "-analyzeduration 5000000 -probesize 131072 "
    "-thread_queue_size 4096 "
    "-fflags +genpts+discardcorrupt "
    "-flags low_delay"
)

_LOCAL_FFMPEG_PARAMS = (
    "-analyzeduration 5000000 -probesize 131072 "
    "-thread_queue_size 4096 "
    "-fflags +genpts+discardcorrupt "
    "-flags low_delay"
)

_REMOTE_FFMPEG_PARAMS_VIDEO = (
    f"{_PROXY_FFMPEG}"
    f"{_RECONNECT_FFMPEG}"
    "-rw_timeout 15000000 "
    "-analyzeduration 5000000 -probesize 131072 "
    "-thread_queue_size 4096 "
    "-fflags +genpts+discardcorrupt "
    "-flags low_delay"
)

_LOCAL_FFMPEG_PARAMS_VIDEO = (
    "-analyzeduration 5000000 -probesize 131072 "
    "-thread_queue_size 4096 "
    "-fflags +genpts+discardcorrupt "
    "-flags low_delay"
)
