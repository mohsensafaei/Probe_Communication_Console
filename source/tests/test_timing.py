"""Minimum-delay and cancellation behavior on coarse Windows asyncio clocks."""
import asyncio
import time
import unittest
from unittest.mock import patch

from probe.timing import sleep_at_least, wait_for


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_delays_and_reply_timeouts_do_not_finish_early(self):
        with patch("probe.timing.COARSE_CLOCK", True):
            started = time.perf_counter()
            for _ in range(6):
                await sleep_at_least(.005)
            self.assertGreaterEqual(time.perf_counter()-started, .03)
            started = time.perf_counter()
            with self.assertRaises(TimeoutError):
                await wait_for(asyncio.Event().wait(), .007)
            self.assertGreaterEqual(time.perf_counter()-started, .007)

    async def test_long_delay_cancellation_and_reply_interrupt(self):
        with patch("probe.timing.COARSE_CLOCK", True):
            task = asyncio.create_task(sleep_at_least(3600))
            await asyncio.sleep(.001)
            started = time.perf_counter()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertLess(time.perf_counter()-started, .25)
            event = asyncio.Event()
            task = asyncio.create_task(wait_for(event.wait(), 3600))
            await asyncio.sleep(0)
            event.set()
            self.assertTrue(await task)
            self.assertFalse([t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()])


class AbsoluteClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_processing_time_does_not_accumulate_and_missed_slots_preserve_phase(self):
        from probe.timing import SequenceClock
        now=[0]
        async def until(deadline):now[0]=max(now[0],deadline)
        with patch('probe.timing.time.perf_counter_ns',side_effect=lambda:now[0]),patch('probe.timing.sleep_until_ns',side_effect=until):
            clock=SequenceClock();points=[]
            for _ in range(10):
                points.append(await clock.before_send());clock.dispatched(now[0]);now[0]+=300000
                await clock.after_send(1)
            self.assertEqual(points,list(range(0,10000000,1000000)))
            self.assertEqual(clock.skipped,0)
            now[0]+=5200000
            target=await clock.before_send();self.assertEqual(target%1000000,0)
            self.assertGreater(clock.skipped,0);self.assertEqual(clock.count,10)

    async def test_absolute_wait_is_cancellable(self):
        from probe.timing import sleep_until_ns
        task=asyncio.create_task(sleep_until_ns(time.perf_counter_ns()+3600*10**9))
        await asyncio.sleep(.001);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
