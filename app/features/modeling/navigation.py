from __future__ import annotations

from contextvars import ContextVar

from telegram.ext import ContextTypes


MODELING_CALLBACK_PREFIX = "modeling"
NAV_CURRENT_KEY = "modeling_nav_current"
NAV_STACK_KEY = "modeling_nav_stack"
NAV_SUPPRESS_KEY = "modeling_nav_suppress"
NAV_BACK_ACTION = "nav_back"
NAV_FALLBACK = f"{MODELING_CALLBACK_PREFIX}:root"
NAV_MAX_DEPTH = 30

_CURRENT_CALLBACK_CONTEXT: ContextVar[ContextTypes.DEFAULT_TYPE | None] = ContextVar(
    "modeling_current_callback_context",
    default=None,
)
_CURRENT_CALLBACK_USER_ID: ContextVar[int | None] = ContextVar(
    "modeling_current_callback_user_id",
    default=None,
)


def nav_back_callback() -> str:
    return f"{MODELING_CALLBACK_PREFIX}:{NAV_BACK_ACTION}"


def set_callback_context(context: ContextTypes.DEFAULT_TYPE | None, user_id: int | None) -> tuple[object, object]:
    context_token = _CURRENT_CALLBACK_CONTEXT.set(context)
    user_token = _CURRENT_CALLBACK_USER_ID.set(int(user_id) if user_id is not None else None)
    return context_token, user_token


def reset_callback_context(tokens: tuple[object, object]) -> None:
    context_token, user_token = tokens
    _CURRENT_CALLBACK_CONTEXT.reset(context_token)
    _CURRENT_CALLBACK_USER_ID.reset(user_token)


def current_callback_context() -> ContextTypes.DEFAULT_TYPE | None:
    return _CURRENT_CALLBACK_CONTEXT.get()


def current_callback_user_id() -> int | None:
    return _CURRENT_CALLBACK_USER_ID.get()


def nav_enter(context: ContextTypes.DEFAULT_TYPE | None, callback_data: str) -> None:
    if context is None:
        return
    callback_data = str(callback_data)
    if context.user_data.pop(NAV_SUPPRESS_KEY, False):
        context.user_data[NAV_CURRENT_KEY] = callback_data
        return

    current = context.user_data.get(NAV_CURRENT_KEY)
    if isinstance(current, str) and current and current != callback_data:
        stack = context.user_data.get(NAV_STACK_KEY)
        if not isinstance(stack, list):
            stack = []
        if not stack or stack[-1] != current:
            stack.append(current)
        context.user_data[NAV_STACK_KEY] = stack[-NAV_MAX_DEPTH:]
    context.user_data[NAV_CURRENT_KEY] = callback_data


def nav_reset(context: ContextTypes.DEFAULT_TYPE | None, current: str | None = None) -> None:
    if context is None:
        return
    context.user_data[NAV_STACK_KEY] = []
    context.user_data.pop(NAV_SUPPRESS_KEY, None)
    if current:
        context.user_data[NAV_CURRENT_KEY] = current
    else:
        context.user_data.pop(NAV_CURRENT_KEY, None)


def nav_pop(context: ContextTypes.DEFAULT_TYPE) -> str:
    current = context.user_data.get(NAV_CURRENT_KEY)
    stack = context.user_data.get(NAV_STACK_KEY)
    if not isinstance(stack, list):
        stack = []

    target = NAV_FALLBACK
    while stack:
        candidate = stack.pop()
        if isinstance(candidate, str) and candidate and candidate != current:
            target = candidate
            break

    context.user_data[NAV_STACK_KEY] = stack[-NAV_MAX_DEPTH:]
    context.user_data[NAV_SUPPRESS_KEY] = True
    return target
