# All rights reserved.

from .Apple import Apple
from .Carbon import Carbon
from .JioSavan import Saavn
from .Resso import Resso
from .Soundcloud import SoundCloud
from .Spotify import Spotify
from .Telegram import Telegram
from .youtube_engine import YouTubeResilient


class PlaTForms:
    def __init__(self):
        self.apple = Apple()
        self.carbon = Carbon()
        self.saavn = Saavn()
        self.resso = Resso()
        self.soundcloud = SoundCloud()
        self.spotify = Spotify()
        self.telegram = Telegram()
        # Centralise all YouTube playback through the resilient engine.
        # The legacy Youtube.py remains available for compatibility, but is no
        # longer selected as the primary playback implementation.
        self.youtube = YouTubeResilient()
