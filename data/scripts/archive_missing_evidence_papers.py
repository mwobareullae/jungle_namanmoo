#!/usr/bin/env python3
"""Fetch exact metadata for second-pass evidence papers into an audit archive."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from discover_new_evidence import PaperMetadata, PubMedClient, normalize_doi
from search_missing_effect_evidence import read_csv
from search_missing_effect_evidence_europe_pmc import EuropePmcClient, EuropePmcPaper


OUTPUT_FIELDS = [
    "paper_key",
    "pmid",
    "doi",
    "source",
    "source_id",
    "title",
    "journal",
    "publication_types",
    "authors",
    "abstract",
    "source_url",
    "retrieved_on",
]


def archive_papers(
    adjudication_rows: list[dict[str, str]],
    *,
    pubmed_client: PubMedClient,
    europe_pmc_client: EuropePmcClient,
    retrieved_on: date,
) -> list[dict[str, str]]:
    paper_keys = sorted({row["paper_key"] for row in adjudication_rows})
    pmids = [key.removeprefix("PMID:") for key in paper_keys if key.startswith("PMID:")]
    pubmed_papers = pubmed_client.fetch(pmids)
    rows: list[dict[str, str]] = []
    for paper_key in paper_keys:
        if paper_key.startswith("PMID:"):
            pmid = paper_key.removeprefix("PMID:")
            paper = pubmed_papers.get(pmid, PaperMetadata(pmid=pmid))
            rows.append(
                {
                    "paper_key": paper_key,
                    "pmid": pmid,
                    "doi": paper.doi,
                    "source": "PubMed",
                    "source_id": pmid,
                    "title": paper.title,
                    "journal": paper.journal,
                    "publication_types": "; ".join(paper.publication_types),
                    "authors": "; ".join(paper.authors),
                    "abstract": paper.abstract,
                    "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "retrieved_on": retrieved_on.isoformat(),
                }
            )
            continue

        doi = normalize_doi(paper_key.removeprefix("DOI:"))
        _, matches = europe_pmc_client.search(f'DOI:"{doi}"', page_size=10)
        paper = next(
            (candidate for candidate in matches if candidate.doi == doi),
            EuropePmcPaper("", "", "", "", doi, "", "", ()),
        )
        rows.append(
            {
                "paper_key": paper_key,
                "pmid": paper.pmid,
                "doi": doi,
                "source": f"EuropePMC:{paper.source}",
                "source_id": paper.source_id,
                "title": paper.title,
                "journal": "",
                "publication_types": "; ".join(paper.publication_types),
                "authors": "",
                "abstract": paper.abstract,
                "source_url": f"https://doi.org/{doi}",
                "retrieved_on": retrieved_on.isoformat(),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adjudication",
        type=Path,
        default=Path(
            "data/reconciliation/ingredient_effect_missing_evidence_adjudication.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/reconciliation/ingredient_effect_missing_evidence_papers.csv"
        ),
    )
    parser.add_argument("--retrieved-on", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    rows = archive_papers(
        read_csv(args.adjudication),
        pubmed_client=PubMedClient(request_delay_seconds=0.5),
        europe_pmc_client=EuropePmcClient(request_delay_seconds=0.25),
        retrieved_on=args.retrieved_on,
    )
    write_csv(args.output, rows)
    print(f"Missing evidence paper archive: papers={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
