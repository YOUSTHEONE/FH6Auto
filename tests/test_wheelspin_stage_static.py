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
        self.assertIn("self.logic_consume_wheelspins", self.source)

    def test_fifth_stage_ui_and_defaults_are_configured(self):
        self.assertIn('"spin_count": 1', self.source)
        self.assertIn('"chk_5": True', self.source)
        self.assertIn('"next_4": 5', self.source)
        self.assertIn('"next_5": 1', self.source)
        self.assertIn('if "next_5" not in data:', self.source)
        self.assertIn('data["next_4"] = 5', self.source)
        self.assertIn('"5. 开抽"', self.source)
        self.assertIn('lambda: self.start_pipeline("spin")', self.source)

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

    def test_spin_stage_presses_enter_quickly_and_returns_to_anchor_area(self):
        self.assertIn("time.sleep(0.1)", self.source)
        self.assertIn("for attempt in range(500):", self.source)
        self.assertGreaterEqual(len(re.findall(r'self\.hw_press\("pagedown"\)', self.source)), 3)
        self.assertIn('self.hw_press("pageup")', self.source)


if __name__ == "__main__":
    unittest.main()
