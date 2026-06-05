from __future__ import annotations

from telegram import Update


class MyDataFlowStore:
    def __init__(self) -> None:
        self._states: dict[tuple[int, int], dict[str, object]] = {}

    @staticmethod
    def _key(chat_id: int, user_id: int) -> tuple[int, int]:
        return int(chat_id), int(user_id)

    def expect(
        self,
        chat_id: int,
        user_id: int,
        action: str,
        message_id: int,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        state: dict[str, object] = {
            "action": action,
            "message_id": int(message_id),
        }
        if payload:
            state["payload"] = dict(payload)
        self._states[self._key(chat_id, user_id)] = state

    def get_action(self, chat_id: int, user_id: int) -> str | None:
        state = self._states.get(self._key(chat_id, user_id))
        value = state.get("action") if state else None
        return value if isinstance(value, str) else None

    def get_message_id(self, chat_id: int, user_id: int) -> int | None:
        state = self._states.get(self._key(chat_id, user_id))
        value = state.get("message_id") if state else None
        return value if isinstance(value, int) else None

    def get_payload(self, chat_id: int, user_id: int) -> dict[str, object]:
        state = self._states.get(self._key(chat_id, user_id))
        value = state.get("payload") if state else None
        return dict(value) if isinstance(value, dict) else {}

    def clear(self, chat_id: int, user_id: int) -> None:
        self._states.pop(self._key(chat_id, user_id), None)


def matches_active_message(update: Update, store: MyDataFlowStore) -> bool:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return False

    if update.effective_chat.type == "private":
        return True

    message_id = store.get_message_id(update.effective_chat.id, update.effective_user.id)
    if message_id is None:
        return False

    reply = update.message.reply_to_message
    return reply is not None and reply.message_id == message_id
