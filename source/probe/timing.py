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


from contextvars import ContextVar
SCHEDULED_NS=ContextVar('probe_scheduled_ns',default=None)


async def sleep_until_ns(deadline_ns):
    """Cancellable absolute deadline; recheck early event-loop wakeups."""
    while (remaining:=deadline_ns-time.perf_counter_ns())>0:
        # Native sleep releases the GIL and avoids selector timeout rounding.
        # Bound a cancelled wait's underlying thread work to 50 ms.
        await asyncio.to_thread(time.sleep,min(remaining/1e9,.05))


class SequenceClock:
    """Fixed phase for intervals. Skip elapsed slots, never drop payloads."""
    def __init__(self):
        self.next_ns=None;self.period_ns=0;self.skipped=0;self.count=0;self.max_late_ns=0;self.total_late_ns=0

    async def before_send(self):
        now=time.perf_counter_ns()
        if self.next_ns is None:self.next_ns=now
        if self.period_ns and now>self.next_ns:
            skipped=(now-self.next_ns)//self.period_ns+1
            self.skipped+=skipped;self.next_ns+=skipped*self.period_ns
        await sleep_until_ns(self.next_ns)
        return self.next_ns

    def dispatched(self,actual_ns):
        late=max(0,actual_ns-self.next_ns);self.count+=1
        self.max_late_ns=max(self.max_late_ns,late);self.total_late_ns+=late

    async def after_send(self,delay_ms,reply_gated=False):
        if reply_gated:
            await sleep_at_least(delay_ms/1000);self.next_ns=None;self.period_ns=0
        else:
            self.period_ns=delay_ms*1000000;self.next_ns+=self.period_ns
            # The next before_send waits once. No trailing interval after the last send.
            await asyncio.sleep(0)

    def summary(self):
        return dict(clock='perf_counter_ns',policy='absolute deadlines; skip elapsed slots, preserve messages',
                    sends=self.count,skipped_slots=self.skipped,max_dispatch_lateness_ns=self.max_late_ns,
                    mean_dispatch_lateness_ns=self.total_late_ns//max(1,self.count))
