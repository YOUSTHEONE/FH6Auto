import unittest

from main import FH_UltimateBot


class FHUltimateBotInterfaceTest(unittest.TestCase):
    def test_exposes_multi_element_image_matcher(self):
        matcher = getattr(FH_UltimateBot, "find_image_with_element_multi", None)

        self.assertTrue(callable(matcher))


if __name__ == "__main__":
    unittest.main()
