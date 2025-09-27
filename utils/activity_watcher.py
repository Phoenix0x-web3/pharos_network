# -*- coding: utf-8 -*-
"""
Activity Watcher — дебаг-декоратор и вотчер для асинхронных задач.
Логирует активные таски и вложенные шаги (stack).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Union
from loguru import logger
import types
import functools as ft


@dataclass
class ActivityState:
    func_name: str
    wallet_hint: str
    thread_name: str
    started_at: float = field(default_factory=time.time)
    stack: list[str] = field(default_factory=list)
    action_since: float = field(default_factory=time.time)

    def age(self) -> int:
        return int(time.time() - self.started_at)

    def action_age(self) -> int:
        return int(time.time() - self.action_since)

    @property
    def current_action(self) -> str:
        return " > ".join(self.stack) if self.stack else "-"


class _ActivityRegistry:
    """Глобальный реестр активных задач."""
    def __init__(self) -> None:
        self._by_task: "weakref.WeakKeyDictionary[asyncio.Task, ActivityState]" = weakref.WeakKeyDictionary()
        self._lock = asyncio.Lock()
        self._watcher_started = False

    async def register(self, task: asyncio.Task, state: ActivityState) -> None:
        async with self._lock:
            self._by_task[task] = state

    async def unregister(self, task: asyncio.Task) -> None:
        async with self._lock:
            self._by_task.pop(task, None)

    async def snapshot(self) -> Dict[int, ActivityState]:
        async with self._lock:
            return {id(t): s for t, s in list(self._by_task.items())}


_REG = _ActivityRegistry()


def _wallet_hint_from_args(args: tuple, kwargs: dict, wallet_kw: str | None = "wallet") -> str:
    """Формируем человекочитаемую подпись кошелька."""
    w = None
    if wallet_kw and wallet_kw in kwargs:
        w = kwargs.get(wallet_kw)
    elif args:
        w = args[0]

    if w is None:
        return "-"

    # Controller → достаем wallet.id
    if hasattr(w, "wallet"):
        inner = getattr(w, "wallet")
        if hasattr(inner, "id"):
            return str(inner.id)
        return str(inner)

    # Wallet напрямую
    if hasattr(w, "id"):
        return str(w.id)

    return str(w)


def debug_activity(wallet_kw: str | None = "wallet"):
    """Декоратор: регистрирует задачу и ведёт stack действий."""
    def _decorator(func):
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@debug_activity работает только с async функциями")

        @functools.wraps(func)
        async def _wrapper(*args, **kwargs):
            task = asyncio.current_task()
            if task is None:
                return await func(*args, **kwargs)

            snap = await _REG.snapshot()
            st = snap.get(id(task))

            if st:
                # вложенный вызов — пушим имя в стек
                st.stack.append(func.__name__)
                st.action_since = time.time()
                try:
                    return await func(*args, **kwargs)
                finally:
                    if st.stack:
                        st.stack.pop()
            else:
                # верхний уровень
                wallet_hint = _wallet_hint_from_args(args, kwargs, wallet_kw)
                st = ActivityState(func_name=func.__name__,
                                   wallet_hint=wallet_hint,
                                   thread_name=threading.current_thread().name)
                st.stack.append(func.__name__)
                await _REG.register(task, st)
                try:
                    return await func(*args, **kwargs)
                finally:
                    await _REG.unregister(task)

        return _wrapper
    return _decorator


def _action_to_str(action: Union[str, Callable[..., Any], Any]) -> str:
    """Превращает action в читаемое имя."""
    # partial
    if isinstance(action, ft.partial):
        return _action_to_str(action.func)

    # bound method
    if isinstance(action, types.MethodType):
        return f"{action.__self__.__class__.__name__}.{action.__func__.__name__}"

    # нормальные функции
    if hasattr(action, "__name__") and action.__name__ != "<lambda>":
        return action.__name__

    if hasattr(action, "__qualname__") and action.__qualname__ != "<lambda>":
        return action.__qualname__

    # лямбды с замыканием → достаём из __closure__
    if hasattr(action, "__name__") and action.__name__ == "<lambda>" and getattr(action, "__closure__", None):
        for c in action.__closure__:
            try:
                val = c.cell_contents
                if callable(val):
                    return _action_to_str(val)
            except Exception:
                pass

    return repr(action)


def mark_action(action: Union[str, Callable[..., Any], Any]) -> None:
    """Помечаем текущий action."""
    task = asyncio.current_task()
    if not task:
        return

    async def _set():
        snap = await _REG.snapshot()
        st = snap.get(id(task))
        if st:
            label = _action_to_str(action)
            if st.stack:
                st.stack[-1] = label
            else:
                st.stack.append(label)
            st.action_since = time.time()

    asyncio.create_task(_set())


def _fmt_state(task_id: int, st: ActivityState, stall_threshold: int) -> str:
    stalled = "  [STALLED]" if st.action_age() >= stall_threshold else ""
    return (
        f"task={task_id} | thread={st.thread_name} | func={st.func_name} "
        f"| wallet={st.wallet_hint} | age={st.age()}s | "
        f"action='{st.current_action}' ({st.action_age()}s){stalled}"
    )


async def start_activity_watcher(interval: int = 30, stall_threshold: int = 2700) -> None:
    """
    Вотчер: каждые interval секунд логирует активные таски.
    stall_threshold — сколько секунд без смены action считаем подвисанием (по умолчанию 45 мин).
    """
    if getattr(_REG, "_watcher_started", False):
        logger.debug("ActivityWatcher: already running")
    else:
        _REG._watcher_started = True
        logger.debug(f"ActivityWatcher: started (interval={interval}s, stall_threshold={stall_threshold}s)")

    while True:
        snap = await _REG.snapshot()
        if snap:
            logger.debug("=== Active Activities ===")
            for tid, st in snap.items():
                logger.debug(_fmt_state(tid, st, stall_threshold))
            logger.debug("=== End Activities ===")
        await asyncio.sleep(interval)
class activity_step:
    """
    Контекстный менеджер: временно помечает action.
    Пример:
        async with activity_step("prepare_twitter"):
            twitter_tasks, discord_tasks = await self.pharos_portal.tasks_flow()
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        self._task = asyncio.current_task()
        if not self._task:
            return
        snap = await _REG.snapshot()
        st = snap.get(id(self._task))
        if st:
            st.stack.append(self.label)
            st.action_since = time.time()

    async def __aexit__(self, exc_type, exc, tb):
        if not self._task:
            return
        snap = await _REG.snapshot()
        st = snap.get(id(self._task))
        if st and st.stack:
            st.stack.pop()
            st.action_since = time.time()
