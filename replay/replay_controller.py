"""Replay speed and state controller."""

from __future__ import annotations

import asyncio
from enum import StrEnum


class ReplayController:
    """Control flow helper for market replay."""

    class State(StrEnum):
        IDLE = "idle"
        RUNNING = "running"
        PAUSED = "paused"
        FINISHED = "finished"

    def __init__(self) -> None:
        self._speed = 1.0
        self._state = self.State.IDLE
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    def set_speed(self, multiplier: float) -> None:
        self._speed = multiplier if multiplier > 0 else 1.0

    def pause(self) -> None:
        self._state = self.State.PAUSED
        self._resume_event.clear()

    def resume(self) -> None:
        self._state = self.State.RUNNING
        self._resume_event.set()

    def stop(self) -> None:
        self._state = self.State.FINISHED
        self._resume_event.set()

    async def wait_for_next_bar(self, bar_interval_seconds: float) -> None:
        if self._state == self.State.PAUSED:
            await self._resume_event.wait()
        if self._state == self.State.FINISHED:
            return
        if self._speed == float("inf"):
            await asyncio.sleep(0)
            return
        await asyncio.sleep(max(bar_interval_seconds / max(self._speed, 1e-9), 0.0))

    @property
    def state(self) -> State:
        return self._state

    @property
    def current_speed(self) -> float:
        return self._speed

    def mark_running(self) -> None:
        self._state = self.State.RUNNING
        self._resume_event.set()

    def mark_idle(self) -> None:
        self._state = self.State.IDLE
        self._resume_event.set()


__all__ = ["ReplayController"]
