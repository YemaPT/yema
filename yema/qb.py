"""Compatibility facade for qBittorrent/PT torrent commands.

Implementation is split across clients, services, storage and UI modules.
"""

from .clients.qbittorrent import *  # noqa: F401,F403
from .clients.yemapt import *  # noqa: F401,F403
from .commands.qb import (  # noqa: F401
    check_torrents,
    pub_torrents,
    qb_command,
    seed_torrents,
)
from .core.debug import *  # noqa: F401,F403
from .core.formatting import *  # noqa: F401,F403
from .core.terminal import *  # noqa: F401,F403
from .domain.trackers import *  # noqa: F401,F403
from .services.torrents import *  # noqa: F401,F403
from .storage.cache import *  # noqa: F401,F403
from .ui.screens import *  # noqa: F401,F403
