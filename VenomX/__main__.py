#
# All rights reserved.
import asyncio
import importlib

from pyrogram import idle
from pytgcalls.exceptions import NoActiveGroupCall

import config
from config import BANNED_USERS
from VenomX import HELPABLE, LOGGER, app, userbot
from VenomX.core.call import Ayush
from VenomX.plugins import ALL_MODULES
from VenomX.utils.database import get_banned_users, get_gbanned
from VenomX.utils.premium import install_text_entities_patch, validate_db

install_text_entities_patch()


async def init():
    if len(config.STRING_SESSIONS) == 0:
        LOGGER("VenomX").error("No Assistant Clients Vars Defined!.. Exiting Process.")
        return False

    if not config.SPOTIFY_CLIENT_ID and not config.SPOTIFY_CLIENT_SECRET:
        LOGGER("VenomX").warning(
            "No Spotify Vars defined. Your bot won't be able to play spotify queries."
        )

    try:
        users = await get_gbanned()
        for user_id in users:
            BANNED_USERS.add(user_id)
        users = await get_banned_users()
        for user_id in users:
            BANNED_USERS.add(user_id)
    except Exception as exc:
        LOGGER("VenomX").warning(f"Could not load ban lists: {type(exc).__name__}: {exc}")

    try:
        await app.start()
        LOGGER("VenomX").info("Validating premium emoji database...")
        try:
            await validate_db(app)
        except Exception:
            LOGGER("VenomX").warning("Could not validate premium emoji database.")

        for all_module in ALL_MODULES:
            imported_module = importlib.import_module(all_module)
            if hasattr(imported_module, "__MODULE__") and imported_module.__MODULE__:
                if hasattr(imported_module, "__HELP__") and imported_module.__HELP__:
                    HELPABLE[imported_module.__MODULE__.lower()] = imported_module

        LOGGER("VenomX.plugins").info("Successfully Imported All Modules")
        await userbot.start()
        await Ayush.start()
        LOGGER("VenomX").info("Assistant Started Successfully")

        # Do not use a sample media stream as a startup dependency.
        # It can create an unnecessary VC join/leave cycle and may fail on
        # logger groups without an active call. Actual /play commands handle
        # voice-call joining and media playback themselves.
        LOGGER("VenomX").info("VenomX Started Successfully")
        await idle()
        return True
    finally:
        # Always cleanly close clients before a restart. This prevents stale
        # Telegram/PyTgCalls sessions when the hosting platform restarts us.
        try:
            await Ayush.stop()
        except Exception as exc:
            LOGGER("VenomX").warning(f"PyTgCalls shutdown warning: {type(exc).__name__}: {exc}")
        try:
            await userbot.stop()
        except Exception as exc:
            LOGGER("VenomX").warning(f"Assistant shutdown warning: {type(exc).__name__}: {exc}")
        try:
            await app.stop()
        except Exception as exc:
            LOGGER("VenomX").warning(f"Bot shutdown warning: {type(exc).__name__}: {exc}")


async def main():
    # Keep the container alive if the Telegram client or PyTgCalls returns
    # cleanly for an unexpected reason. A normal container stop/SIGTERM is
    # still handled by the host; this loop is for unexpected clean exits.
    restart_delay = 5
    while True:
        try:
            running = await init()
            if running is False:
                LOGGER("VenomX").error("Initialization failed permanently; check STRING_SESSIONS and configuration.")
                return
            LOGGER("VenomX").warning(
                f"VenomX event loop ended unexpectedly. Restarting in {restart_delay}s..."
            )
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            LOGGER("VenomX").exception(
                f"VenomX crashed unexpectedly: {type(exc).__name__}: {exc}. Restarting in {restart_delay}s..."
            )
        await asyncio.sleep(restart_delay)


if __name__ == "__main__":
    try:
        app.run(main())
    finally:
        LOGGER("VenomX").info("Stopping VenomX! GoodBye")
