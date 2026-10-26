"""Cancellable minimum delays, including Windows' coarse asyncio clock.

CPython <=3.12 can schedule asyncio callbacks a full monotonic-clock tick early.
Use the high-resolution performance clock to measure durations. On coarse clocks,
short worker sleeps avoid spinning and bound cancellation cleanup to 50 ms.
"""
import asyncio
from collections.abc import Awaitable
import time
from typing import TypeVar

T = TypeVar("T")
COARSE_CLOCK = time.get_clock_info("monotonic").resolution > .001


async def sleep_at_least(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    if seconds <= 0:
        await asyncio.sleep(0)
        return
    while (remaining := deadline - time.perf_counter()) > 0:
        if COARSE_CLOCK:
            # A cancelled hour-long test must not leave an hour-long executor job.
            await asyncio.to_thread(time.sleep, min(remaining, .05))
        else:
            await asyncio.sleep(remaining)


async def wait_for(awaitable: Awaitable[T], seconds: float) -> T:
    """Wait for a reply/reset without expiring before the requested duration."""
    operation = asyncio.ensure_future(awaitable)
    timer = asyncio.create_task(sleep_at_least(seconds))
    try:
        done, _ = await asyncio.wait((operation, timer), return_when=asyncio.FIRST_COMPLETED)
        if operation in done:
            return operation.result()
        timer.result()
        raise TimeoutError
    finally:
        operation.cancel()
        timer.cancel()
        await asyncio.gather(operation, timer, return_exceptions=True)
