from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fresh_pubmed_search_v1_1 import (  # noqa: E402
    PubMedSearchError,
    build_approved_terms,
    build_query,
    pagination_status,
    parse_pubmed_xml,
)


class FreshPubMedSearchV11Tests(unittest.TestCase):
    def test_terms_use_canonical_and_reviewed_high_confidence_aliases_only(self) -> None:
        result = build_approved_terms(
            {"bht"},
            [{"ingredient_id": "bht", "name_en": "BHT", "source_url": "master"}],
            [
                {
                    "canonical_id": "bht",
                    "alias": "Butylated Hydroxytoluene|Di-tert-butyl-p-cresol",
                    "alias_type": "synonym",
                    "confidence": "high",
                    "source": "approved",
                },
                {
                    "canonical_id": "bht",
                    "alias": "unreviewed term",
                    "alias_type": "synonym",
                    "confidence": "medium",
                    "source": "proposal",
                },
                {
                    "canonical_id": "bht",
                    "alias": "비에이치티",
                    "alias_type": "ko",
                    "confidence": "high",
                    "source": "approved",
                },
            ],
        )
        self.assertEqual(
            [item.term for item in result["bht"]],
            ["BHT", "Butylated Hydroxytoluene", "Di-tert-butyl-p-cresol"],
        )

    def test_no_ingredient_id_fallback_is_allowed(self) -> None:
        with self.assertRaises(PubMedSearchError):
            build_approved_terms(
                {"synthetic_id"},
                [{"ingredient_id": "synthetic_id", "name_en": ""}],
                [],
            )

    def test_query_contains_only_ingredient_and_skin_context_clauses(self) -> None:
        query = build_query(["Niacinamide", "Nicotinamide"])
        self.assertIn('"Niacinamide"[Title/Abstract]', query)
        self.assertIn('"Nicotinamide"[Title/Abstract]', query)
        self.assertIn('"skin"[Title/Abstract]', query)
        self.assertNotIn("melanin", query.casefold())
        self.assertNotIn("wrinkle", query.casefold())
        self.assertNotIn("acne", query.casefold())

    def test_pagination_status_distinguishes_complete_capped_and_incomplete(self) -> None:
        self.assertEqual(pagination_status(8, 8, 100), ("complete", "Y"))
        self.assertEqual(
            pagination_status(101, 100, 100),
            ("capped_at_retrieval_limit", "N"),
        )
        self.assertEqual(
            pagination_status(8, 7, 100),
            ("incomplete_response", "N"),
        )

    def test_pubmed_xml_parser_preserves_basic_metadata(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <PubmedArticleSet><PubmedArticle><MedlineCitation>
          <PMID>12345678</PMID><Article><ArticleTitle>Topical test</ArticleTitle>
          <Abstract><AbstractText>Measured result.</AbstractText></Abstract>
          <Journal><Title>Journal</Title><JournalIssue><PubDate><Year>2025</Year>
          <Month>07</Month><Day>01</Day></PubDate></JournalIssue></Journal>
          <AuthorList><Author><LastName>Kim</LastName><Initials>R</Initials></Author></AuthorList>
          <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType>
          </PublicationTypeList></Article></MedlineCitation><PubmedData><ArticleIdList>
          <ArticleId IdType='doi'>10.1/example</ArticleId></ArticleIdList></PubmedData>
        </PubmedArticle></PubmedArticleSet>"""
        paper = parse_pubmed_xml(payload)["12345678"]
        self.assertEqual(paper.doi, "10.1/example")
        self.assertEqual(paper.title, "Topical test")
        self.assertEqual(paper.publication_date, "2025-07-01")
        self.assertEqual(paper.authors, ("Kim R",))
        self.assertEqual(paper.abstract, "Measured result.")

    def test_pubmed_book_xml_parser_preserves_basic_metadata(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <PubmedArticleSet><PubmedBookArticle><BookDocument>
          <PMID>20301297</PMID><ArticleIdList><ArticleId IdType='bookaccession'>NBK1</ArticleId>
          </ArticleIdList><Book><BookTitle>GeneReviews</BookTitle><CollectionTitle>NCBI Bookshelf</CollectionTitle><PubDate><Year>2026</Year>
          </PubDate></Book><ArticleTitle>Book chapter</ArticleTitle>
          <AuthorList Type='authors'><Author><LastName>Kim</LastName><Initials>R</Initials>
          </Author></AuthorList><PublicationType>Review</PublicationType>
          <Abstract><AbstractText>Chapter abstract.</AbstractText></Abstract>
        </BookDocument></PubmedBookArticle></PubmedArticleSet>"""
        paper = parse_pubmed_xml(payload)["20301297"]
        self.assertEqual(paper.title, "GeneReviews")
        self.assertEqual(paper.journal, "NCBI Bookshelf")
        self.assertEqual(paper.publication_date, "2026")
        self.assertEqual(paper.publication_types, ("Review",))
        self.assertEqual(paper.authors, ("Kim R",))


if __name__ == "__main__":
    unittest.main()
