import asyncio
import hashlib
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import get_comfy_servers


@dataclass
class BackendState:
    url: str
    priority: int = 1
    healthy: bool = False
    queue_running: int = 0
    queue_pending: int = 0
    latency_ms: Optional[int] = None
    active_requests: int = 0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    last_checked: float = 0.0
    last_error: Optional[str] = None

    @property
    def queue_total(self) -> int:
        return self.queue_running + self.queue_pending


class BackendManager:
    """Maintain lightweight ComfyUI health state and choose a backend from cached data."""

    def __init__(self):
        self.poll_interval = max(0.5, float(os.environ.get("ORANGE_BACKEND_POLL_SECONDS", "2")))
        self.probe_timeout = max(0.5, float(os.environ.get("ORANGE_BACKEND_PROBE_TIMEOUT", "2")))
        self.failure_threshold = max(1, int(os.environ.get("ORANGE_BACKEND_FAILURE_THRESHOLD", "3")))
        self.backoff_seconds = max(1.0, float(os.environ.get("ORANGE_BACKEND_BACKOFF_SECONDS", "15")))
        self._states: Dict[str, BackendState] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._workflow_compatibility: Dict[str, Dict[str, bool]] = {}

    def _sync_servers(self) -> None:
        configured = []
        for server in get_comfy_servers():
            url = str(server.get("url", "")).strip().rstrip("/")
            if not url:
                continue
            try:
                priority = int(server.get("priority", 1))
            except (TypeError, ValueError):
                priority = 1
            configured.append((url, priority))

        configured_urls = {url for url, _ in configured}
        for url in list(self._states):
            if url not in configured_urls:
                del self._states[url]

        for url, priority in configured:
            state = self._states.get(url)
            if state is None:
                self._states[url] = BackendState(url=url, priority=priority)
            else:
                state.priority = priority

        for compatibility in self._workflow_compatibility.values():
            for url in list(compatibility):
                if url not in configured_urls:
                    del compatibility[url]

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
            self._client = httpx.AsyncClient(timeout=self.probe_timeout, limits=limits)
        return self._client

    async def start(self) -> None:
        await self._ensure_client()
        self._sync_servers()
        await self.refresh_all()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop(), name="orange-backend-monitor")

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            try:
                await self.refresh_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"Backend monitor refresh failed: {exc}")

    async def _probe(self, state: BackendState) -> None:
        now = time.monotonic()
        if state.circuit_open_until > now:
            return

        client = await self._ensure_client()
        started = time.perf_counter()
        try:
            response = await client.get(f"{state.url}/queue", timeout=self.probe_timeout)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Queue response was not an object")

            running = data.get("queue_running", [])
            pending = data.get("queue_pending", [])
            state.queue_running = len(running) if isinstance(running, list) else 0
            state.queue_pending = len(pending) if isinstance(pending, list) else 0
            state.latency_ms = round((time.perf_counter() - started) * 1000)
            state.healthy = True
            state.consecutive_failures = 0
            state.circuit_open_until = 0.0
            state.last_error = None
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.record_failure(state.url, str(exc))
            state.latency_ms = round((time.perf_counter() - started) * 1000)
        finally:
            state.last_checked = time.time()

    async def refresh_all(self) -> None:
        self._sync_servers()
        states = list(self._states.values())
        if states:
            await asyncio.gather(*(self._probe(state) for state in states))

    async def refresh_url(self, url: str) -> None:
        self._sync_servers()
        normalized = str(url).rstrip("/")
        state = self._states.get(normalized)
        if state is not None:
            await self._probe(state)

    def record_failure(self, url: str, error: Optional[str] = None) -> None:
        normalized = str(url).rstrip("/")
        state = self._states.get(normalized)
        if state is None:
            return
        state.healthy = False
        state.consecutive_failures += 1
        state.last_error = error or "Backend request failed"
        if state.consecutive_failures >= self.failure_threshold:
            state.circuit_open_until = time.monotonic() + self.backoff_seconds

    def record_success(self, url: str) -> None:
        normalized = str(url).rstrip("/")
        state = self._states.get(normalized)
        if state is None:
            return
        state.healthy = True
        state.consecutive_failures = 0
        state.circuit_open_until = 0.0
        state.last_error = None

    def increment_active(self, url: str) -> None:
        state = self._states.get(str(url).rstrip("/"))
        if state is not None:
            state.active_requests += 1

    def decrement_active(self, url: str) -> None:
        state = self._states.get(str(url).rstrip("/"))
        if state is not None:
            state.active_requests = max(0, state.active_requests - 1)

    def record_preflight(self, compatibility_key: str, backend_results: List[dict]) -> None:
        if not compatibility_key:
            return
        compatibility = self._workflow_compatibility.setdefault(compatibility_key, {})
        for result in backend_results:
            url = str(result.get("url", "")).strip().rstrip("/")
            if not url or not result.get("reachable"):
                continue
            compatibility[url] = not bool(result.get("errors"))

    def _eligible_states(
        self,
        exclude_urls: Optional[List[str]] = None,
        compatibility_key: Optional[str] = None,
    ) -> List[BackendState]:
        excluded = {str(url).rstrip("/") for url in (exclude_urls or [])}
        compatibility = self._workflow_compatibility.get(compatibility_key or "", {})
        now = time.monotonic()

        eligible = []
        for state in self._states.values():
            if state.url in excluded:
                continue
            if not state.healthy or state.circuit_open_until > now:
                continue
            if compatibility.get(state.url) is False:
                continue
            eligible.append(state)
        return eligible

    @staticmethod
    def _score(state: BackendState) -> tuple:
        effective_queue = state.queue_total + state.active_requests
        latency = state.latency_ms if state.latency_ms is not None else 10**9
        return effective_queue, state.priority, latency, state.url

    async def get_best_backend(
        self,
        exclude_urls: Optional[List[str]] = None,
        compatibility_key: Optional[str] = None,
    ) -> Optional[str]:
        await self._ensure_client()
        self._sync_servers()

        if self._states and not any(state.last_checked for state in self._states.values()):
            await self.refresh_all()

        candidates = self._eligible_states(exclude_urls, compatibility_key)
        if not candidates:
            await self.refresh_all()
            candidates = self._eligible_states(exclude_urls, compatibility_key)
        if not candidates:
            return None

        return min(candidates, key=self._score).url

    async def get_client(self) -> httpx.AsyncClient:
        return await self._ensure_client()

    def snapshot(self) -> List[dict]:
        self._sync_servers()
        now_monotonic = time.monotonic()
        now_wall = time.time()
        rows = []
        for state in sorted(self._states.values(), key=lambda item: (item.priority, item.url)):
            circuit_seconds = max(0.0, state.circuit_open_until - now_monotonic)
            rows.append(
                {
                    "url": state.url,
                    "priority": state.priority,
                    "healthy": state.healthy,
                    "queue_running": state.queue_running,
                    "queue_pending": state.queue_pending,
                    "queue_total": state.queue_total,
                    "active_requests": state.active_requests,
                    "latency_ms": state.latency_ms,
                    "consecutive_failures": state.consecutive_failures,
                    "circuit_open": circuit_seconds > 0,
                    "circuit_seconds_remaining": round(circuit_seconds, 1),
                    "last_checked": state.last_checked or None,
                    "last_checked_age_seconds": round(now_wall - state.last_checked, 1) if state.last_checked else None,
                    "last_error": state.last_error,
                }
            )
        return rows


def workflow_compatibility_key(workflow_file: str, workflow: Any, node_mapping: Any) -> str:
    payload = {
        "workflow_file": workflow_file or "",
        "workflow": workflow,
        "node_mapping": node_mapping or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


backend_manager = BackendManager()


async def get_backend_queue_size(url: str) -> float:
    await backend_manager.refresh_url(url)
    state = backend_manager._states.get(str(url).rstrip("/"))
    if state is None or not state.healthy:
        return float("inf")
    return float(state.queue_total)


async def get_best_backend(
    exclude_urls: Optional[List[str]] = None,
    compatibility_key: Optional[str] = None,
) -> Optional[str]:
    return await backend_manager.get_best_backend(exclude_urls, compatibility_key)


def increment_active(url: str) -> None:
    backend_manager.increment_active(url)


def decrement_active(url: str) -> None:
    backend_manager.decrement_active(url)


def report_backend_failure(url: str, error: Optional[str] = None) -> None:
    backend_manager.record_failure(url, error)


def report_backend_success(url: str) -> None:
    backend_manager.record_success(url)


async def get_backend_client() -> httpx.AsyncClient:
    return await backend_manager.get_client()
