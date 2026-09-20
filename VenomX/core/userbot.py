# All rights reserved.
#
import asyncio

from pyrogram import Client
from pyrogram.errors import ChatWriteForbidden
import config
from ..logging import LOGGER

assistants = []
assistantids = []


class Userbot(Client):
    def __init__(self):
        self.clients = []
        self.sessions = config.STRING_SESSIONS
        for i, session in enumerate(self.sessions, start=1):
            self.clients.append(Client(
                f"VenomString{i}",
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                in_memory=True,
                no_updates=True,
                session_string=session.strip(),
            ))

    async def _start(self, client, index):
        LOGGER(__name__).info("Starting Assistant Clients")
        try:
            await client.start()
            if index not in assistants:
                assistants.append(index)
            get_me = await client.get_me()
            client.username = get_me.username
            client.id = get_me.id
            client.mention = get_me.mention
            if get_me.id not in assistantids:
                assistantids.append(get_me.id)
            client.name = f"{get_me.first_name} {get_me.last_name or ''}".strip()
            assistant_msg = (
                "╔══════════════════════╗\n"
                "  🤖 **ᴀssɪsᴛᴀɴᴛ sᴛᴀʀᴛᴇᴅ** 🤖\n"
                "╚══════════════════════╝\n\n"
                f"🧑 **ɴᴀᴍᴇ:** {client.name}\n"
                f"🔑 **ɪᴅ:** <code>{client.id}</code>\n"
                f"🔗 **ᴜsᴇʀɴᴀᴍᴇ:** @{client.username}\n"
                f"🔢 **ɪɴsᴛᴀɴᴄᴇ:** #{index}\n"
                "📡 **sᴛᴀᴛᴜs:** ✅ ᴀᴄᴛɪᴠᴇ\n"
                "🎵 **ʀᴏʟᴇ:** ᴠᴏɪᴄᴇᴄʜᴀᴛ ᴀssɪsᴛᴀɴᴛ\n"
            )
            try:
                await client.send_message(config.LOGGER_ID, assistant_msg)
            except ChatWriteForbidden:
                try:
                    await client.join_chat(config.LOGGER_ID)
                    await client.send_message(config.LOGGER_ID, assistant_msg)
                except Exception as exc:
                    LOGGER(__name__).error(f"Assistant {index} could not write to logger: {exc}")
                    # Logger delivery must never kill a working assistant.
        except Exception as e:
            LOGGER(__name__).error(f"Assistant Account {index} failed with error: {e}")
            # Do not sys.exit() from an individual assistant task.  A bad logger,
            # transient Telegram error, or one invalid session must not kill the bot.
            raise

    async def start(self):
        if not self.clients:
            raise RuntimeError("No assistant string sessions configured")
        results = await asyncio.gather(
            *(self._start(client, i) for i, client in enumerate(self.clients, start=1)),
            return_exceptions=True,
        )
        failures = [r for r in results if isinstance(r, Exception)]
        if len(failures) == len(self.clients):
            raise RuntimeError(f"All assistant sessions failed: {failures[0]}")
        if failures:
            LOGGER(__name__).warning(f"{len(failures)} assistant session(s) failed; continuing with healthy assistants")

    async def stop(self):
        await asyncio.gather(*(client.stop() for client in self.clients), return_exceptions=True)

    def __getattr__(self, name):
        if not self.clients:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        first_client = self.clients[0]
        if hasattr(first_client, name):
            return getattr(first_client, name)
        raise AttributeError(f"'{type(first_client).__name__}' object has no attribute '{name}'")
