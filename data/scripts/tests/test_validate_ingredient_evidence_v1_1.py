from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_ingredient_evidence_v1_1 import (  # noqa: E402
    REQUIRED_RAW_SOURCES,
    SOURCES,
    _integer,
    _summary_count,
)


class ValidateIngredientEvidenceV11Tests(unittest.TestCase):
    def test_numeric_zero_is_not_treated_as_missing(self) -> None:
        self.assertEqual(_integer(0), 0)
        self.assertEqual(
            _summary_count({"candidate_row_count": 0}, kind="candidates"),
            0,
        )

    def test_all_six_sources_require_raw_packages(self) -> None:
        self.assertEqual(REQUIRED_RAW_SOURCES, SOURCES)
        self.assertIn("kci", REQUIRED_RAW_SOURCES)
        self.assertIn("riss", REQUIRED_RAW_SOURCES)


if __name__ == "__main__":
    unittest.main()
