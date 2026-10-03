"""Two loopback listeners, one Finder event loop, separate public/internal routes."""

import os
import socket
from contextlib import ExitStack
from pathlib import Path

import uvicorn
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .app import create_app
from .discord_api import create_internal


class Listeners:
    def __init__(self, public, internal):
        self.public = public
        self.proxy_public = ProxyHeadersMiddleware(public, trusted_hosts=["127.0.0.1"])
        self.internal = internal

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.public(scope, receive, send)
        elif scope.get("server", (None, None))[1] == 8781:
            await self.internal(scope, receive, send)
        else:
            await self.proxy_public(scope, receive, send)


def main():
    public = create_app()
    secret = Path(os.environ["MITHRIL_DISCORD_SECRET_FILE"]).read_text().strip()
    app = Listeners(public, create_internal(public, secret))
    config = uvicorn.Config(app, access_log=False, proxy_headers=False, workers=1)
    with ExitStack() as stack:
        sockets = []
        for port in (8780, 8781):
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            option = socket.SO_EXCLUSIVEADDRUSE if os.name == "nt" else socket.SO_REUSEADDR
            listener.setsockopt(socket.SOL_SOCKET, option, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            sockets.append(listener)
        uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
