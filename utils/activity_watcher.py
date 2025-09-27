# -*- coding: utf-8 -*-
"""
Activity Watcher — дебаг-декоратор и вотчер для асинхронных задач.
Стиль: минимальные зависимости, loguru, совместимо с архитектурой проекта.

Использование:
    from utils.activity_watcher import debug_activity, start_activity_watcher, mark_action

    @debug_activity()                   # повесь на random_activity_task
    async def random_activity_task(...):
        ...
        for action in actions:
            mark_action(action)         # помечаем какой экшен сейчас исполняем
            await action()              # дальше как обычно
        ...

    # запусти вотчер один раз при старте приложения:
    asyncio.create_task(start_activity_watcher(interval=30, stall_threshold=180))
"""

from __future__ import annotations

import asyncio
import time
import threading
import inspect
import functools
import weakref
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Union, Dict

from loguru import logger


@dataclass
class ActivityState:
    func_name: str
    wallet_hint: str
    thread_name: str
    started_at: float = field(default_factory=time.time)
    action: str = "-"
    action_since: float = field(default_factory=time.time)

    def age(self) -> int:
        return int(time.time() - self.started_at)

    def action_age(self) -> int:
        return int(time.time() - self.action_since)


class _ActivityRegistry:
    """Глобальный реестр активных задач (safe к отменам/GC)."""
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

    async def set_action(self, task: asyncio.Task, action: str) -> None:
        async with self._lock:
            st = self._by_task.get(task)
            if st:
                st.action = action
                st.action_since = time.time()

    async def snapshot(self) -> Dict[int, ActivityState]:
        # возвращаем копию (id(task) -> state)
        async with self._lock:
            return {id(t): s for t, s in list(self._by_task.items())}


_REG = _ActivityRegistry()


def _wallet_hint_from_args(args: tuple, kwargs: dict, wallet_kw: str | None = "wallet") -> str:
    """Формируем человекочитаемую подпись кошелька для логов."""
    w = None

    # сначала пробуем достать по имени
    if wallet_kw and wallet_kw in kwargs:
        w = kwargs.get(wallet_kw)
    elif args:
        w = args[0]

    if w is None:
        return "-"

    # если это Controller — забираем wallet.id
    if hasattr(w, "wallet") and hasattr(w.wallet, "id"):
        return str(w.wallet.id)

    # если это Wallet напрямую
    if hasattr(w, "id"):
        return str(w.id)

    return str(w)

def debug_activity(wallet_kw: str | None = "wallet"):
    """
    Декоратор для async-функций: регистрирует задачу в реестре, чтобы вотчер видел её состояние.
    По умолчанию wallet берётся из первого позиционного аргумента, либо kwargs['wallet'].
    """
    def _decorator(func: Callable[..., Any]):
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@debug_activity работает только с async функциями")

        @functools.wraps(func)
        async def _wrapper(*args, **kwargs):
            task = asyncio.current_task()
            if task is None:
                # крайне маловероятно, но на всякий случай
                return await func(*args, **kwargs)

            state = ActivityState(
                func_name=func.__name__,
                wallet_hint=_wallet_hint_from_args(args, kwargs, wallet_kw),
                thread_name=threading.current_thread().name,
            )
            await _REG.register(task, state)
            try:
                return await func(*args, **kwargs)
            finally:
                await _REG.unregister(task)

        return _wrapper
    return _decorator


def _fmt_state(task_id: int, st: ActivityState, stall_threshold: int) -> str:
    stalled = "  [STALLED]" if st.action_age() >= stall_threshold else ""
    return (
        f"task={task_id} | thread={st.thread_name} | func={st.func_name} | wallet={st.wallet_hint} | "
        f"age={st.age()}s | action='{st.action}' ({st.action_age()}s){stalled}"
    )


async def start_activity_watcher(interval: int = 30, stall_threshold: int = 120) -> None:
    """
    Фоновая корутина: каждые `interval` секунд логирует активные задачи.
    `stall_threshold` — сколько секунд без смены action считаем «подвисло».
    Вешай один раз на всё приложение: asyncio.create_task(start_activity_watcher(...))
    """
    # Сделаем вотчер идемпотентным: если уже запущен — просто крутим цикл.
    # Это защищает от повторных create_task(...) в сложной инициализации.
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

import types, functools
def _action_to_str(action):
    import inspect, types
    import re


    if isinstance(action, functools.partial):
        return _action_to_str(action.func)

    # bound method
    if isinstance(action, types.MethodType):
        return f"{action.__self__.__class__.__name__}.{action.__func__.__name__}"


    if hasattr(action, "__name__") and action.__name__ != "<lambda>":
        return action.__name__


    if hasattr(action, "__name__") and action.__name__ == "<lambda>" and action.__closure__:
        for c in action.__closure__:
            try:
                val = c.cell_contents
                if callable(val):
                    return _action_to_str(val)
            except Exception:
                pass


    try:
        src = inspect.getsource(action).strip()
        m = re.search(r"self\.([a-zA-Z0-9_\.]+)", src)
        if m:
            return m.group(1)
        return f"<lambda:{src}>"
    except Exception:
        return repr(action)

def mark_action(action: Union[str, Callable[..., Any], Any]) -> None:
    """
    Помечает текущий экшен для *текущей* корутины (изнутри декорированной функции).
    Вызов перед `await action()`: mark_action(action)
    """
    task = asyncio.current_task()
    if task is None:
        return
    label = _action_to_str(action)
    # fire-and-forget: не блокируем текущий поток
    asyncio.create_task(_REG.set_action(task, label))


# (опционально) контекст-менеджер, если удобнее в сложных местах:
class activity_step:
    """
    with activity_step("prepare_swap"):
        ...
    """
    def __init__(self, label: str) -> None:
        self.label = label
        self._task: Optional[asyncio.Task] = None
        self._prev: Optional[str] = None

    async def __aenter__(self):
        self._task = asyncio.current_task()
        if self._task:
            snap = await _REG.snapshot()
            st = snap.get(id(self._task))
            if st:
                self._prev = st.action
        mark_action(self.label)

    async def __aexit__(self, exc_type, exc, tb):
        if self._prev:
            mark_action(self._prev)
