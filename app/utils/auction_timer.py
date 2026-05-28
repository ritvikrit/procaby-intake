import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_auction_tasks: dict[str, asyncio.Task] = {}


async def start_auction_countdown(
    event_id: str,
    end_time: datetime,
    on_expire: Callable[[str], Awaitable[None]],
) -> None:
    if event_id in _auction_tasks and not _auction_tasks[event_id].done():
        logger.warning(f"Auction timer for {event_id} already running.")
        return

    task = asyncio.create_task(_countdown(event_id, end_time, on_expire))
    _auction_tasks[event_id] = task
    logger.info(f"Auction timer started for {event_id}, expires at {end_time.isoformat()}")


async def _countdown(
    event_id: str,
    end_time: datetime,
    on_expire: Callable[[str], Awaitable[None]],
) -> None:
    now = datetime.now(timezone.utc)
    remaining = (end_time - now).total_seconds()

    if remaining > 0:
        await asyncio.sleep(remaining)

    logger.info(f"Auction {event_id} expired. Triggering close.")
    try:
        await on_expire(event_id)
    except Exception as exc:
        logger.error(f"Error in auction expiry handler for {event_id}: {exc}")
    finally:
        _auction_tasks.pop(event_id, None)


def cancel_auction_timer(event_id: str) -> None:
    task = _auction_tasks.pop(event_id, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"Auction timer cancelled for {event_id}.")
