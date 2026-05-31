from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
IMAGES = ROOT / "images"


class SellRemovalStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")

    def test_required_sell_templates_exist(self):
        required = [
            "sell_22b_card_full.png",
            "sell_22b_car_crop.png",
            "sell_22b_title.png",
            "sell_b600.png",
            "sell_legendary_orange.png",
            "sell_detail_subaru_logo.png",
            "sell_detail_legendary_orange.png",
            "sell_detail_b600.png",
            "sell_detail_price_86000.png",
            "sell_remove_button_white.png",
            "sell_remove_button_black.png",
            "sell_remove_confirm_yes_white.png",
            "sell_remove_confirm_yes_black.png",
        ]
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((IMAGES / filename).exists(), filename)

    def test_sell_flow_uses_two_stage_verification(self):
        self.assertIn("def find_sell_target_22b_card(self):", self.source)
        self.assertIn("def verify_sell_target_detail_panel(self):", self.source)
        self.assertIn("def remove_selected_verified_sell_car(self):", self.source)
        self.assertIn("find_sell_target_22b_card()", self.source)
        self.assertIn("verify_sell_target_detail_panel()", self.source)
        self.assertIn("remove_selected_verified_sell_car()", self.source)

    def test_old_brittle_delete_match_is_removed(self):
        self.assertNotIn('threshold=0.98', self.source)
        self.assertNotIn('"D.png",\n                    region=self.regions["左"]', self.source)

    def test_grid_candidate_requires_identity_b600_and_legendary(self):
        for filename in [
            "sell_22b_card_full.png",
            "sell_22b_car_crop.png",
            "sell_22b_title.png",
            "sell_b600.png",
            "sell_legendary_orange.png",
        ]:
            with self.subTest(filename=filename):
                self.assertIn(filename, self.source)
        self.assertIn("required_hits >= 2", self.source)
        self.assertIn("identity_hit", self.source)

    def test_detail_panel_requires_price_and_subaru(self):
        for filename in [
            "sell_detail_subaru_logo.png",
            "sell_detail_legendary_orange.png",
            "sell_detail_b600.png",
            "sell_detail_price_86000.png",
        ]:
            with self.subTest(filename=filename):
                self.assertIn(filename, self.source)
        self.assertIn("detail_hits == len(detail_checks)", self.source)

    def test_remove_action_uses_button_images(self):
        self.assertIn("sell_remove_button_white.png", self.source)
        self.assertIn("sell_remove_button_black.png", self.source)
        self.assertIn("sell_remove_confirm_yes_white.png", self.source)
        self.assertIn("sell_remove_confirm_yes_black.png", self.source)
        self.assertIn("未识别到从车库移除按钮，停止以避免误删", self.source)
        self.assertIn("未识别到移除确认按钮，停止以避免误删", self.source)


if __name__ == "__main__":
    unittest.main()
