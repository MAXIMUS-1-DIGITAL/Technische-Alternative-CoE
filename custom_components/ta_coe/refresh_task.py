"""CoE server value refresh task."""
import asyncio

from ta_cmi import ApiError

from .const import _LOGGER

REFRESH_INTERVAL = 10 * 60


class RefreshTask:
    """Handle the refresh of values to the CoE server."""

    def __init__(self, sender):
        """Initialize."""
        self._sender = sender
        self._task: asyncio.Task | None = None

    @property
    def is_started(self) -> bool:
        """Return True while the refresh loop is running."""
        return self._task is not None and not self._task.done()

    async def start(self):
        """Start the task."""
        _LOGGER.debug("Try to start refresh task")
        if not self.is_started:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        """Stop the task. Never raises: a dead task must not block the unload."""
        _LOGGER.debug("Try to stop refresh task")
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as err:  # noqa: BLE001 - logged, unload must go on
            _LOGGER.warning("Refresh task had ended with an error: %s", err)

    async def _run(self):
        """Run action."""
        _LOGGER.info("Refresh task started")
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            if not self._sender.has_entities():
                continue
            try:
                await self._sender.update()
            except ApiError as err:
                _LOGGER.warning(
                    "CoE server not reachable, next try in %s s: %s", REFRESH_INTERVAL, err
                )
            except Exception:  # noqa: BLE001 - keep the loop alive
                _LOGGER.exception("Unexpected error while sending values to the CoE server")
