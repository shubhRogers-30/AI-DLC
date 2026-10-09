import asyncio

class RunStore:
    def __init__(self):
        self._runs = {}
        self._lock = asyncio.Lock()

    async def put(self, run_id, value):
        async with self._lock:
            self._runs[run_id] = value

    async def get(self, run_id):
        async with self._lock:
            return self._runs.get(run_id)

store = RunStore()
