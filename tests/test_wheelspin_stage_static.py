from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


class WheelspinStageStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")

    def test_pipeline_includes_spin_as_fifth_stage(self):
        self.assertIn('steps = ["race", "buy", "cj", "sell", "spin"]', self.source)
        self.assertIn('elif step_name == "spin":', self.source)
        self.assertIn("self.logic_consume_wheelspins()", self.source)

    def test_fifth_stage_ui_and_defaults_are_configured(self):
        self.assertIn('"chk_5": True', self.source)
        self.assertIn('"next_4": 5', self.source)
        self.assertIn('"next_5": 1', self.source)
        self.assertIn('if "next_5" not in data:', self.source)
        self.assertIn('data["next_4"] = 5', self.source)
        self.assertIn('"5. 开抽"', self.source)
        self.assertIn('lambda: self.start_pipeline("spin")', self.source)
        self.assertNotIn('"spin_count": 1', self.source)
        self.assertNotIn("self.entry_spin", self.source)
        self.assertNotIn("self.lbl_spin", self.source)

    def test_next_step_controls_are_embedded_in_stage_cards(self):
        self.assertIn("def add_next_step(parent, var_checked, def_step):", self.source)
        self.assertIn("add_next_step(box_race, self.var_chk1", self.source)
        self.assertIn("add_next_step(box_car, self.var_chk2", self.source)
        self.assertIn("add_next_step(self.box_cj, self.var_chk3", self.source)
        self.assertIn("add_next_step(box_sc, self.var_chk4", self.source)
        self.assertIn("add_next_step(box_spin, self.var_chk5", self.source)
        self.assertNotIn("def create_next_step(", self.source)
        self.assertNotIn("self.next_frame", self.source)

    def test_next_step_validation_allows_five_steps(self):
        self.assertRegex(self.source, r"if iv > 5:\s+iv = 5")
        self.assertRegex(self.source, r"min\(4,\s*int\(self\.entry_next5\.get\(\)\)\s*-\s*1\)")

    def test_wheelspin_templates_are_referenced(self):
        for filename in [
            "SuperWheelSpin.png",
            "WheelSpin.png",
            "NoSuperSpinsLeft.png",
            "NoSpinsLeft.png",
        ]:
            with self.subTest(filename=filename):
                self.assertIn(filename, self.source)

    def test_empty_super_spins_transition_to_regular_spins(self):
        self.assertIn('return "empty"', self.source)
        self.assertIn('super_result = self.consume_single_wheelspin_type("SuperWheelSpin.png", "NoSuperSpinsLeft.png", "超级抽奖")', self.source)
        self.assertIn("if super_result is False:", self.source)
        self.assertIn('regular_result = self.consume_single_wheelspin_type("WheelSpin.png", "NoSpinsLeft.png", "普通抽奖")', self.source)
        self.assertIn("if regular_result is False:", self.source)

    def test_menu_return_after_spin_type_is_treated_as_empty(self):
        self.assertRegex(
            self.source,
            r"if menu_seen:\s+self\.log\(f\"\{log_name\}已回到抽奖菜单，切换下一类抽奖\"\)\s+return \"empty\"",
        )

    def test_spin_stage_spams_enter_in_batches_before_image_checks(self):
        self.assertRegex(
            self.source,
            r"for _ in range\(50\):\s+if not self\.is_running:\s+return False\s+self\.hw_press\(\"enter\", delay=0\.02\)\s+time\.sleep\(0\.1\)",
        )
        self.assertRegex(
            self.source,
            r"if self\.find_image\(empty_image, region=self\.regions\[\"全界面\"\], threshold=0\.75, fast_mode=True\):\s+empty_seen = True\s+break",
        )
        self.assertIn("for attempt in range(500):", self.source)
        self.assertGreaterEqual(len(re.findall(r'self\.hw_press\("pagedown"\)', self.source)), 3)
        self.assertIn('self.hw_press("pageup")', self.source)


if __name__ == "__main__":
    unittest.main()
