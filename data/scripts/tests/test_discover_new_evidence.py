from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from discover_new_evidence import (  # noqa: E402
    CANDIDATE_FIELDS,
    KnownEvidence,
    PaperMetadata,
    PubMedClient,
    build_pair_query,
    build_summary,
    discover_candidates,
    load_ingredient_terms,
    load_known_evidence,
    normalize_doi,
    parse_pubmed_xml,
    read_csv_rows,
    split_english_name,
    write_candidates,
)


class FakeResponse:
    def __init__(self, payload: bytes = b"", error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        if self.error:
            raise self.error
        return self.payload


class RetryOpener:
    def __init__(self) -> None:
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(error=TimeoutError("read timed out"))
        return FakeResponse(payload=b"ok")


class FakePubMedClient:
    def __init__(self) -> None:
        self.request_count = 0
        self.retry_count = 0

    def search(self, query, *, window_start, window_end, retmax):
        self.request_count += 1
        if '"hyperpigmentation"' in query:
            return ["11111111", "22222222"]
        if '"acne"' in query:
            return ["11111111", "33333333", "44444444"]
        return []

    def fetch(self, pmids):
        self.request_count += 1
        papers = {
            "11111111": PaperMetadata(
                pmid="11111111",
                doi="10.1000/known",
                title="Known paper, newly considered for acne",
            ),
            "22222222": PaperMetadata(
                pmid="22222222",
                doi="10.1000/new",
                title="New brightening paper",
                journal="Journal of Skin Tests",
                publication_date="2026-07-10",
                publication_types=("Clinical Trial",),
                authors=("Jane Doe",),
                abstract="A short abstract.",
            ),
            "33333333": PaperMetadata(
                pmid="33333333",
                doi="10.1000/elsewhere",
                title="Known elsewhere",
            ),
            "44444444": PaperMetadata(
                pmid="44444444",
                doi="https://doi.org/10.1000/pair-duplicate)",
                title="DOI duplicate for this pair",
            ),
        }
        return {pmid: papers[pmid] for pmid in pmids}


class EvidenceDiscoveryTests(unittest.TestCase):
    def test_pubmed_client_retries_response_read_timeout(self):
        opener = RetryOpener()
        client = PubMedClient(
            opener=opener,
            request_delay_seconds=0,
            max_retries=1,
        )

        payload = client._request("efetch.fcgi", {"db": "pubmed", "id": "1"})

        self.assertEqual(payload, b"ok")
        self.assertEqual(client.retry_count, 1)
        self.assertEqual(opener.calls, 2)

    def test_current_72_pair_contract_builds_queries_without_network(self):
        repo_root = SCRIPT_DIR.parents[1]
        pairs = read_csv_rows(repo_root / "data/ingredient_effect.csv")
        ingredient_ids = {row["ingredient_id"] for row in pairs}
        terms = load_ingredient_terms(
            read_csv_rows(repo_root / "data/ingredients.csv"),
            read_csv_rows(repo_root / "data/ingredient_aliases.csv"),
            ingredient_ids,
        )

        self.assertEqual(len(pairs), 72)
        self.assertEqual(set(terms), ingredient_ids)
        for row in pairs:
            query = build_pair_query(terms[row["ingredient_id"]], row["effect_id"])
            self.assertIn("[Title/Abstract]", query)

    def test_normalize_doi_strips_url_prefix_and_trailing_punctuation(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1000/ABC.123)."),
            "10.1000/abc.123",
        )

    def test_ingredient_terms_exclude_ambiguous_abbreviation_aliases(self):
        terms = load_ingredient_terms(
            [
                {
                    "ingredient_id": "salicylic_acid_bha",
                    "name_en": "Salicylic Acid",
                }
            ],
            [
                {
                    "canonical_id": "salicylic_acid_bha",
                    "alias": "BHA",
                    "alias_type": "abbrev",
                    "confidence": "high",
                },
                {
                    "canonical_id": "salicylic_acid_bha",
                    "alias": "Beta Hydroxy Acid",
                    "alias_type": "synonym",
                    "confidence": "high",
                },
            ],
            {"salicylic_acid_bha"},
        )

        self.assertIn("Salicylic Acid", terms["salicylic_acid_bha"])
        self.assertIn("Beta Hydroxy Acid", terms["salicylic_acid_bha"])
        self.assertNotIn("BHA", terms["salicylic_acid_bha"])

        query = build_pair_query(terms["salicylic_acid_bha"], "effect_acne_sebum")
        self.assertIn('"acne"[Title/Abstract]', query)
        self.assertIn('"skin"[Title/Abstract]', query)

    def test_parse_pubmed_xml_preserves_metadata_and_structured_abstract(self):
        payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22222222</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><Year>2026</Year><Month>Jul</Month></PubDate></JournalIssue>
          <Title>Journal of Skin Tests</Title>
        </Journal>
        <ArticleTitle>A <i>topical</i> skin study</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background text.</AbstractText>
          <AbstractText Label="RESULTS">Result text.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><ForeName>Jane</ForeName><LastName>Doe</LastName></Author>
          <Author><CollectiveName>Study Group</CollectiveName></Author>
        </AuthorList>
        <PublicationTypeList><PublicationType>Clinical Trial</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/ABC</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""
        paper = parse_pubmed_xml(payload)["22222222"]

        self.assertEqual(paper.title, "A topical skin study")
        self.assertEqual(paper.doi, "10.1000/abc")
        self.assertEqual(paper.publication_date, "2026-Jul")
        self.assertEqual(paper.publication_types, ("Clinical Trial",))
        self.assertEqual(paper.authors, ("Jane Doe", "Study Group"))
        self.assertEqual(
            paper.abstract,
            "BACKGROUND: Background text. RESULTS: Result text.",
        )

    def test_discovery_deduplicates_per_pair_but_keeps_known_paper_for_new_pair(self):
        pairs = [
            {
                "ingredient_id": "niacinamide",
                "effect_id": "effect_brightening",
                "effect_name": "미백·톤",
            },
            {
                "ingredient_id": "niacinamide",
                "effect_id": "effect_acne_sebum",
                "effect_name": "여드름·피지",
            },
        ]
        known = load_known_evidence(
            [
                {
                    "ingredient_id": "niacinamide",
                    "effect_id": "effect_brightening",
                    "pmid": "11111111",
                    "doi": "10.1000/known",
                },
                {
                    "ingredient_id": "centella_asiatica",
                    "effect_id": "effect_calming",
                    "pmid": "33333333",
                    "doi": "10.1000/elsewhere",
                },
                {
                    "ingredient_id": "niacinamide",
                    "effect_id": "effect_acne_sebum",
                    "pmid": "",
                    "doi": "10.1000/pair-duplicate",
                },
            ]
        )
        client = FakePubMedClient()

        candidates, stats, queries = discover_candidates(
            pair_rows=pairs,
            ingredient_terms={"niacinamide": ["Niacinamide", "Nicotinamide"]},
            known=known,
            client=client,
            window_start=date(2026, 7, 3),
            window_end=date(2026, 7, 10),
            retmax_per_pair=50,
        )

        by_pmid = {row["pmid"]: row for row in candidates}
        self.assertEqual(set(by_pmid), {"11111111", "22222222", "33333333"})
        self.assertEqual(by_pmid["22222222"]["discovery_scope"], "new_paper")
        self.assertEqual(by_pmid["11111111"]["discovery_scope"], "known_paper_new_pair")
        self.assertEqual(by_pmid["33333333"]["discovery_scope"], "known_paper_new_pair")
        self.assertTrue(all(row["review_status"] == "candidate_unverified" for row in candidates))
        self.assertTrue(all(row["score_eligible"] == "false" for row in candidates))
        self.assertTrue(all(row["discovery_key"].startswith("PMID:") for row in candidates))
        self.assertEqual(stats.known_pair_duplicates, 2)
        self.assertEqual(stats.candidate_pair_count, 3)
        self.assertEqual(stats.unique_candidate_papers, 3)
        self.assertEqual(len(queries), 2)

    def test_empty_output_still_has_stable_schema_and_safety_summary(self):
        stats = type(
            "Stats",
            (),
            {
                "pair_count": 72,
                "candidate_pair_count": 0,
                "unique_candidate_papers": 0,
                "known_pair_duplicates": 0,
                "request_count": 72,
                "retry_count": 0,
            },
        )()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidates.csv"
            write_candidates(output, [])
            with output.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames or ()), CANDIDATE_FIELDS)
                self.assertEqual(list(reader), [])

        summary = build_summary(
            stats=stats,
            candidates=[],
            window_start=date(2026, 7, 3),
            window_end=date(2026, 7, 10),
        )
        self.assertIn("자동 점수 반영: **0건**", summary)
        self.assertIn("새 후보가 없습니다", summary)

    def test_slash_in_exact_inci_name_is_not_split_into_generic_terms(self):
        self.assertEqual(
            split_english_name("Jasminum Officinale Flower/Leaf Extract"),
            ["Jasminum Officinale Flower/Leaf Extract"],
        )
        self.assertEqual(
            split_english_name("Capsicum Annuum Extract|Capsicum Frutescens Extract"),
            ["Capsicum Annuum Extract", "Capsicum Frutescens Extract"],
        )


if __name__ == "__main__":
    unittest.main()
