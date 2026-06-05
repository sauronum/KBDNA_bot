from __future__ import annotations

import unittest

from app.features.modeling.menu import build_modeling_keyboard, build_source_sets_keyboard, modeling_placeholder_text, modeling_text, source_sets_text


class ModelingUiTests(unittest.TestCase):
    def test_modeling_is_clean_formal_modeling_shell(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("🧱 AdmixLab", modeling_text("ru"))
        self.assertIn("Формальные модели: qpAdm, qpWave, sources и outgroups.", modeling_text("ru"))
        self.assertIn("🏛 qpAdm", labels)
        self.assertIn("〰️ qpWave", labels)
        self.assertIn("📚 Source sets", labels)
        self.assertIn("💾 Saved models", labels)
        self.assertNotIn("🧩 Source fitting", labels)
        self.assertNotIn("Modeling", modeling_text("ru"))

    def test_modeling_source_sets_is_formal_placeholder(self) -> None:
        text = source_sets_text(lang="ru")
        labels = [button.text for row in build_source_sets_keyboard(lang="ru").inline_keyboard for button in row]

        self.assertIn("Наборы sources и outgroups для формальных моделей.", text)
        self.assertIn("Функция пока не подключена.", text)
        self.assertEqual(labels, ["⬅️ Назад", "Отмена"])
        self.assertNotIn("Steppe", text)
        self.assertNotIn("Karachay-Balkar hypothesis", text)

    def test_modeling_placeholders_use_admixlab_copy(self) -> None:
        qpadm = modeling_placeholder_text("qpadm", "ru")
        qpwave = modeling_placeholder_text("qpwave", "ru")
        source_sets = modeling_placeholder_text("source_sets", "ru")
        saved = modeling_placeholder_text("saved", "ru")

        self.assertIn("🏛 qpAdm", qpadm)
        self.assertIn("Формальная проверка модели через target, sources и outgroups.", qpadm)
        self.assertIn("Функция пока не подключена.", qpadm)
        self.assertIn("〰️ qpWave", qpwave)
        self.assertIn("Проверка числа потоков происхождения между группами.", qpwave)
        self.assertIn("📚 Source sets", source_sets)
        self.assertIn("Наборы sources и outgroups для формальных моделей.", source_sets)
        self.assertIn("💾 Saved models", saved)
        self.assertIn("Сохранённые результаты AdmixLab.", saved)
        self.assertIn("Пока нет сохранённых моделей.", saved)

    def test_old_source_fitting_callback_copy_redirects_to_vahaduo(self) -> None:
        text = modeling_placeholder_text("source_fitting", "ru")

        self.assertIn("Готовые G25-модели теперь находятся в Vahaduo Lab.", text)
        self.assertIn("Откройте Vahaduo Lab → Ready models.", text)


if __name__ == "__main__":
    unittest.main()
