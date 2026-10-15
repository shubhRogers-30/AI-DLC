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

    async def update(self, run_id, **changes):
        async with self._lock:
            item = self._runs.get(run_id)
            if item is None:
                return None
            self._runs[run_id] = {**item, **changes}
            return self._runs[run_id]

    async def claim_approval(self, run_id):
        async with self._lock:
            item = self._runs.get(run_id)
            if not item or item.get("phase") != "awaiting_approval":
                return False
            self._runs[run_id] = {**item, "phase": "running", "pending_approval": None}
            return True

    async def add_event(self, run_id, event):
        async with self._lock:
            item = self._runs.get(run_id)
            if not item:
                return None
            events = list(item.get("events", []))
            event = {"id": len(events) + 1, **event}
            self._runs[run_id] = {**item, "events": events + [event]}
            return event

store = RunStore()
