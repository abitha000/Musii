# All rights reserved.

import asyncio
from typing import Union

from config import autoclean, chatstats, userstats
from config.config import time_to_seconds
from VenomX.misc import db


async def _prefetch_youtube(vidid: str, stream: str):
    """Warm the next YouTube direct URL without delaying queue insertion."""
    if not vidid or not str(vidid).strip():
        return
    if stream not in ("audio", "video"):
        return
    try:
        from VenomX import Platform
        await Platform.youtube.prefetch(vidid, video=(stream == "video"))
    except Exception:
        # Prefetch is an optimization only. Playback always retains its normal
        # extraction/download fallback path.
        return


async def put_queue(
    chat_id: int,
    original_chat_id: int,
    file: str,
    title: str,
    duration: str,
    user: str,
    vidid: str,
    user_id: int,
    stream: str,
    url: str = None,
    forceplay: Union[bool, str] = False,
):
    title = title.title()

    try:
        duration_in_seconds = max(time_to_seconds(duration) - 3, 0)
    except Exception:
        duration_in_seconds = 0

    if chat_id not in db:
        db[chat_id] = []

    if vidid in ("soundcloud", "saavn"):
        vidid = "telegram"

    put = {
        "title": title,
        "dur": duration,
        "streamtype": stream,
        "by": user,
        "chat_id": original_chat_id,
        "file": file,
        "vidid": vidid,
        "seconds": duration_in_seconds,
        "played": 0,
        "url": url,
    }

    if forceplay and db[chat_id]:
        db[chat_id].insert(1, put)
    else:
        db[chat_id].append(put)

    autoclean.append(file)

    if chat_id not in chatstats:
        chatstats[chat_id] = []
    chatstats[chat_id].append({"vidid": vidid, "title": title})

    if user_id not in userstats:
        userstats[user_id] = []
    userstats[user_id].append({"chat_id": chat_id, "title": title})

    # Start prefetch after the queue item is safely stored. Never await it here;
    # a slow YouTube response must not block Telegram queue operations.
    if len(db[chat_id]) > 1 and str(vidid).strip() and str(vidid) != "telegram":
        asyncio.create_task(_prefetch_youtube(str(vidid), str(stream)))

    return len(db[chat_id])


async def put_queue_index(
    chat_id: int,
    original_chat_id: int,
    file: str,
    title: str,
    duration: str,
    user: str,
    vidid: str,
    stream: str,
    forceplay: Union[bool, str] = False,
):
    if chat_id not in db:
        db[chat_id] = []

    if vidid in ("soundcloud", "saavn"):
        vidid = "telegram"

    put = {
        "title": title.title(),
        "dur": duration,
        "streamtype": stream,
        "by": user,
        "chat_id": original_chat_id,
        "file": file,
        "vidid": vidid,
        "seconds": 0,
        "played": 0,
    }

    if forceplay and db[chat_id]:
        db[chat_id].insert(1, put)
    else:
        db[chat_id].append(put)

    if len(db[chat_id]) > 1 and str(vidid).strip() and str(vidid) != "telegram":
        asyncio.create_task(_prefetch_youtube(str(vidid), str(stream)))

    return len(db[chat_id])
