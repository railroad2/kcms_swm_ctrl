#!/usr/bin/env python3

"""
daq_client_sync.py

Synchronous wrapper for the async DAQClient.

This wrapper is intended for:
- traditional blocking DAQ scripts
- simple command-line tools
- test scripts

It is NOT ideal for environments that already run an asyncio event loop.
"""

import asyncio
from typing import Any, Dict, List, Optional, Union

from daq_client import DAQClient, PinInput


class DAQClientSync:
    """
    Synchronous wrapper around async DAQClient.

    Usage
    -----
    client = DAQClientSync("ws://127.0.0.1:8765")
    client.connect()
    client.on("A00")
    client.off("A00")
    labels = client.active_labels()
    client.close()
    """

    def __init__(
        self,
        uri: str,
        *,
        timeout: float = 5.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.uri = uri
        self.timeout = timeout
        self.connect_timeout = connect_timeout

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[DAQClient] = None
        self._connected = False

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """
        Create a dedicated event loop if needed.

        A dedicated loop keeps the sync wrapper self-contained and avoids
        repeated asyncio.run() calls.
        """
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _ensure_client(self) -> DAQClient:
        """Create async client if needed."""
        if self._client is None:
            self._client = DAQClient(
                self.uri,
                timeout=self.timeout,
                connect_timeout=self.connect_timeout,
            )
        return self._client

    def _run(self, coro):
        """
        Run one coroutine on the dedicated event loop.

        If Ctrl+C happens while the coroutine is running, cancel the task
        cleanly and collect its exception so that asyncio does not print:

            Task exception was never retrieved
        """
        loop = self._ensure_loop()
        task = loop.create_task(coro)

        try:
            return loop.run_until_complete(task)

        except KeyboardInterrupt:
            # Cancel the currently running task and make sure its result
            # is collected before re-raising KeyboardInterrupt.
            if not task.done():
                task.cancel()

            try:
                loop.run_until_complete(
                    asyncio.gather(task, return_exceptions=True)
                )
            except Exception:
                pass

            raise

    def _require_client(self) -> DAQClient:
        """Return connected client or raise."""
        if self._client is None or not self._connected:
            raise RuntimeError("DAQClientSync is not connected")
        return self._client

    def _shutdown_loop(self) -> None:
        """
        Cancel pending tasks and close the dedicated loop cleanly.

        This prevents noisy warnings such as:
            Task exception was never retrieved
        during Ctrl+C shutdown paths.
        """
        if self._loop is None:
            return

        loop = self._loop

        try:
            pending = asyncio.all_tasks(loop)
        except Exception:
            pending = set()

        if pending:
            for task in pending:
                task.cancel()

            try:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            except Exception:
                pass

        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass

        loop.close()
        self._loop = None

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the gateway."""
        client = self._ensure_client()
        self._run(client.connect())
        self._connected = True

    def close(self) -> None:
        """Close websocket connection and event loop."""
        try:
            if self._client is not None and self._connected:
                try:
                    self._run(self._client.close())
                except Exception:
                    # Suppress close-time transport noise during shutdown.
                    pass
                self._connected = False
        finally:
            self._shutdown_loop()
            self._client = None

    def __enter__(self) -> "DAQClientSync":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -----------------------------------------------------------------
    # Gateway commands
    # -----------------------------------------------------------------

    def gateway_ping(self) -> Dict[str, Any]:
        """Ping the gateway itself."""
        client = self._require_client()
        return self._run(client.gateway_ping())

    def get(self) -> Dict[str, Any]:
        """Get cached or fetched PINSTAT ALL from gateway."""
        client = self._require_client()
        return self._run(client.get())

    def pin_map(self) -> Dict[str, int]:
        """Get matrix label -> linear pin map from gateway."""
        client = self._require_client()
        return self._run(client.pin_map())

    def subscribe(self) -> Dict[str, Any]:
        """Subscribe to state updates."""
        client = self._require_client()
        return self._run(client.subscribe())

    def unsubscribe(self) -> Dict[str, Any]:
        """Unsubscribe from state updates."""
        client = self._require_client()
        return self._run(client.unsubscribe())

    def recv_event(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Receive one asynchronous event.

        If timeout is None, wait indefinitely.
        """
        client = self._require_client()
        return self._run(client.recv_event(timeout=timeout))

    # -----------------------------------------------------------------
    # Pico commands
    # -----------------------------------------------------------------

    def ping(self) -> Dict[str, Any]:
        """Ping Pico."""
        client = self._require_client()
        return self._run(client.ping())

    def on(self, *pins: PinInput) -> Dict[str, Any]:
        """Turn ON one or more pins."""
        client = self._require_client()
        return self._run(client.on(*pins))

    def off(self, *pins: PinInput) -> Dict[str, Any]:
        """Turn OFF one or more pins."""
        client = self._require_client()
        return self._run(client.off(*pins))

    def alloff(self) -> Dict[str, Any]:
        """Turn OFF all pins."""
        client = self._require_client()
        return self._run(client.alloff())

    def route(self, *target: PinInput) -> Dict[str, Any]:
        """Exclusive route selection."""
        client = self._require_client()
        return self._run(client.route(*target))

    def pinstat(self, which: Union[str, int] = "ALL") -> Dict[str, Any]:
        """Query PINSTAT."""
        client = self._require_client()
        return self._run(client.pinstat(which))

    def pcfstat(self, which: Union[str, int] = "ALL") -> Dict[str, Any]:
        """Query PCFSTAT."""
        client = self._require_client()
        return self._run(client.pcfstat(which))

    # -----------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------

    def active_pins(self) -> List[int]:
        """Return currently active linear pin indices."""
        client = self._require_client()
        return self._run(client.active_pins())

    def active_labels(self) -> List[str]:
        """Return currently active matrix labels."""
        client = self._require_client()
        return self._run(client.active_labels())
