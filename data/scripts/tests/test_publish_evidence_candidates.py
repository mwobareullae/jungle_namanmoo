from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from publish_evidence_candidates import (  # noqa: E402
    PublishError,
    publish_candidates,
    read_candidate_payload,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class PublishEvidenceCandidatesTests(unittest.TestCase):
    def test_reads_csv_as_candidate_unverified_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidates.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "discovery_key",
                        "ingredient_id",
                        "effect_id",
                        "pmid",
                        "title",
                        "source_url",
                        "discovery_scope",
                        "abstract_available",
                        "review_status",
                        "score_eligible",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "discovery_key": "PMID:1:niacinamide:effect_brightening",
                        "ingredient_id": "niacinamide",
                        "effect_id": "effect_brightening",
                        "pmid": "1",
                        "title": "Candidate",
                        "source_url": "https://pubmed.ncbi.nlm.nih.gov/1/",
                        "discovery_scope": "new_paper",
                        "abstract_available": "true",
                        "review_status": "accepted",
                        "score_eligible": "true",
                    }
                )
            payload = read_candidate_payload(path)

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["review_status"], "candidate_unverified")
        self.assertFalse(candidate["score_eligible"])
        self.assertTrue(candidate["abstract_available"])

    def test_posts_json_without_logging_token(self):
        captured = {}

        def opener(request, *, timeout):
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return FakeResponse({"received": 1, "inserted": 1, "refreshed": 0})

        result = publish_candidates(
            endpoint="https://api.example.test/api/internal/evidence-candidates/import",
            token="secret-token",
            payload={"candidates": [{"pmid": "1"}]},
            opener=opener,
        )

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(captured["body"]["candidates"][0]["pmid"], "1")
        self.assertEqual(captured["headers"]["X-evidence-ingest-token"], "secret-token")

    def test_rejects_missing_configuration(self):
        with self.assertRaises(PublishError):
            publish_candidates(endpoint="", token="", payload={"candidates": [{}]})


if __name__ == "__main__":
    unittest.main()
