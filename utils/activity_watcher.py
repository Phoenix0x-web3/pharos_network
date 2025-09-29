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
import types
import dis
import re

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



def _action_to_str(action):
    """Возвращает человекочитаемое имя экшена, включая лямбды вида `lambda: self.foo.bar(...)`."""
    # 1) partial → к исходной функции
    if isinstance(action, ft.partial):
        return _action_to_str(action.func)

    # 2) bound method
    if isinstance(action, types.MethodType):
        try:
            return f"{action.__self__.__class__.__name__}.{action.__func__.__name__}"
        except Exception:
            return getattr(action, "__qualname__", getattr(action, "__name__", repr(action)))

    # 3) нормальные функции
    name = getattr(action, "__name__", None)
    qname = getattr(action, "__qualname__", None)
    if name and name != "<lambda>":
        return name
    if qname and qname != "<lambda>":
        return qname

    # 4) лямбда: разбираем путь self.xxx.yyy через байткод
    if callable(action) and getattr(action, "__name__", "") == "<lambda>":
        try:
            code = action.__code__
            freevars = code.co_freevars or ()
            closure = action.__closure__ or ()
            env = {n: c.cell_contents for n, c in zip(freevars, closure)}
            self_obj = env.get("self", None)

            # Собираем последовательность LOAD_ATTR/LOAD_METHOD до первого вызова
            attrs = []
            for ins in dis.get_instructions(action):
                op = ins.opname
                if op in ("LOAD_ATTR", "LOAD_METHOD"):
                    attrs.append(ins.argval)
                elif op in ("CALL_FUNCTION", "CALL_METHOD", "CALL", "PRECALL", "RETURN_VALUE"):
                    break

            if self_obj is not None and attrs:
                # Пример: self.pns.mint → "PNS.mint"
                return f"{self_obj.__class__.__name__}." + ".".join(attrs)

            # Иногда в замыкании лежит сразу bound-callable (редко, но бывает)
            if closure:
                for cell in closure:
                    try:
                        val = cell.cell_contents
                        if callable(val):
                            return _action_to_str(val)
                    except Exception:
                        pass

            # fallback: попытка вытащить имя из исходника лямбды
            try:
                src = inspect.getsource(action).strip().splitlines()[0]
                m = re.search(r"self\.([A-Za-z_][A-Za-z0-9_\.]*)", src)
                if m:
                    if self_obj is not None:
                        return f"{self_obj.__class__.__name__}.{m.group(1)}"
                    return m.group(1)
                return "<lambda>"
            except Exception:
                return "<lambda>"

        except Exception:
            return "<lambda>"

    # 5) на крайний случай
    return repr(action)

def _name_from_coro(coro) -> str:
    """
    Пытаемся получить Class.method из корутины:
    - coro.cr_code.co_name → имя функции (method)
    - coro.cr_frame.f_locals.get('self') → экземпляр класса
    """
    try:
        code = getattr(coro, "cr_code", None)
        frame = getattr(coro, "cr_frame", None)
        if code is None and hasattr(coro, "gi_code"):     # резерв для генераторов
            code = coro.gi_code
        if frame is None and hasattr(coro, "gi_frame"):
            frame = coro.gi_frame

        fn_name = code.co_name if code else None
        cls_name = None
        if frame and "self" in frame.f_locals:
            cls_name = frame.f_locals["self"].__class__.__name__

        if fn_name and cls_name:
            return f"{cls_name}.{fn_name}"
        if fn_name:
            return fn_name
    except Exception:
        pass
    return repr(coro)

def mark_action(action_or_coro) -> None:
    """
    Помечаем текущий action.
    Поддерживает:
      - корутины (предпочтительно: точное имя через cr_code/cr_frame)
      - функции/лямбды/partial/методы (фоллбек)
    """
    task = asyncio.current_task()
    if not task:
        return

    async def _set():
        snap = await _REG.snapshot()
        st = snap.get(id(task))
        if not st:
            return

        if inspect.iscoroutine(action_or_coro):
            label = _name_from_coro(action_or_coro)
        else:
            label = _action_to_str(action_or_coro)

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
