"""Start and stop the webhook server in a background thread."""

from __future__ import annotations

import logging
import threading

import uvicorn

from ..db.repository import Repository

logger = logging.getLogger(__name__)


class WebhookServerRunner:
    """Manages the lifecycle of the FastAPI webhook server.

    Runs uvicorn in a daemon thread so it terminates automatically
    when the main process exits.
    """

    def __init__(self, host: str, port: int, repo: Repository) -> None:
        self._host = host
        self._port = port
        self._repo = repo
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the webhook server in a background thread."""
        from .server import app

        # Inject the shared repository into the FastAPI app state
        app.state.repo = self._repo

        config = uvicorn.Config(
            app,
            host=self._host,
            port=self._port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(
            target=self._server.run,
            name="webhook-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("Webhook server started on %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Signal the server to shut down."""
        if self._server:
            self._server.should_exit = True
            logger.info("Webhook server shutdown requested")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
