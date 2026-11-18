"""Bound synchronous work, including work that outlives a cancelled await."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore


class BoundedExecutor:
    def __init__(self, name: str, workers: int, capacity: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._slots = BoundedSemaphore(capacity)

    async def run(self, func, *args):
        if not self._slots.acquire(blocking=False):
            raise TimeoutError("Verification worker capacity exhausted")

        def work():
            try:
                return func(*args)
            finally:
                self._slots.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(self._pool, work)
        except BaseException:
            self._slots.release()
            raise
        # Cancellation stops the wait. The thread releases its slot only when it finishes.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(future)


verification_workers = BoundedExecutor("verialign-verification", workers=4, capacity=12)
