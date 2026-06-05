from __future__ import annotations

from types import SimpleNamespace
import unittest

from handlers import lookup as lookup_handlers


class FakeLookupMessage:
    def __init__(self) -> None:
        self.replies: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []
        self._next_message_id = 100

    async def reply_text(self, text: str, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id)

    async def reply_photo(self, **kwargs):
        self.photos.append({"kwargs": kwargs})
        self._next_message_id += 1
        return SimpleNamespace(message_id=self._next_message_id)


class LookupHandlersTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_lookup_records_stores_button_state_for_multiple_records(self) -> None:
        message = FakeLookupMessage()
        context = SimpleNamespace(user_data={})
        records = [
            {"text": "first", "button_label": "G2a · 1"},
            {"text": "second", "button_label": "R1a · 1"},
        ]

        await lookup_handlers.send_lookup_records(
            message=message,
            context=context,
            title_name="абаза",
            records=records,
            use_buttons=True,
        )

        self.assertEqual(message.replies[0]["text"], "<b>АБАЗА</b>\n\nВыберите вариант:")
        self.assertIn("reply_markup", message.replies[0]["kwargs"])
        self.assertEqual(
            context.user_data["lookup_result_options"][101],
            {"records": records, "remaining_indexes": [0, 1]},
        )

    async def test_send_lookup_records_sends_single_record_without_state(self) -> None:
        message = FakeLookupMessage()
        context = SimpleNamespace(user_data={})

        await lookup_handlers.send_lookup_records(
            message=message,
            context=context,
            title_name="абаза",
            records=[{"text": "only", "button_label": "G2a · 1"}],
            use_buttons=True,
        )

        self.assertEqual(message.replies[0]["text"], "only")
        self.assertNotIn("lookup_result_options", context.user_data)

    async def test_send_lookup_records_sends_text_when_visual_fields_are_present(self) -> None:
        message = FakeLookupMessage()
        context = SimpleNamespace(user_data={})

        await lookup_handlers.send_lookup_records(
            message=message,
            context=context,
            title_name="Эркенов",
            records=[{
                "text": "legacy text",
                "button_label": "G2a · 1",
                "visual_name": "Эркенов",
                "visual_haplogroup": "G2a - Z31455",
                "visual_general": "G2a",
                "visual_subclade": "Z31455",
                "visual_origins": ["Карачай"],
                "visual_related": ["Абаев", "Боташев"],
                "visual_test_count": "1",
                "visual_yfull_link": "https://www.yfull.com/tree/G-Z31455/",
            }],
            use_buttons=True,
        )

        self.assertEqual(message.photos, [])
        self.assertEqual(message.replies[0]["text"], "legacy text")
        self.assertEqual(message.replies[0]["kwargs"]["parse_mode"], "HTML")


if __name__ == "__main__":
    unittest.main()
