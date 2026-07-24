#!/usr/bin/env python3
"""Build an ingredient-first paper and measured-outcome review catalog.

The pipeline never pre-creates ingredient x six-effect pairs. It searches by
exact ingredient name and skin context, selects at most three useful papers per
ingredient, preserves original outcome sentences, and maps outcomes only after
paper selection. All outputs are review-only and do not modify runtime scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from effect_direction_dictionary import (
    DIRECTION_POLICY_VERSION,
    assess_outcome_directions,
    summarize_direction_assessments,
)
from effect_outcome_dictionary import APPROVED_MAPPING_TERMS, match_effect_ids
from discover_new_evidence import (
    DEFAULT_REQUEST_DELAY_SECONDS,
    DEFAULT_TOOL_NAME,
    PaperMetadata,
    PubMedClient,
    load_ingredient_terms,
    pubmed_title_abstract_term,
)
from screen_effect_review_candidates import (
    ALL_HISTORY_START,
    IN_VITRO_RE,
    PaperAssessment,
    assess_paper_candidate,
    normalize_phrase,
)
from search_missing_effect_evidence import (
    EXPANDED_EFFECT_TERMS,
    EXPANDED_SKIN_CONTEXT_TERMS,
)


PIPELINE_VERSION = "mwbl-ingredient-first-paper-catalog-v2-role-preserving"
DEFAULT_TARGET_COUNT = 500
DEFAULT_MAX_PAPERS_PER_INGREDIENT = 3
DEFAULT_RETMAX_PER_INGREDIENT = 50

AMBIGUOUS_SEARCH_TERMS = {
    "alcohol",
    "aqua",
    "collagen water",
    "fragrance",
    "parfum",
    "pca",
    "water",
}

# Compatibility name retained for audits. Mapping terms are intentionally
# narrower than discovery vocabulary and are loaded from the reviewed CSV.
EXISTING_EFFECT_MAPPING_TERMS: dict[str, tuple[str, ...]] = APPROVED_MAPPING_TERMS

RESULT_RE = re.compile(
    r"\b(improv(?:e|ed|es|ing)|reduc(?:e|ed|es|ing)|decreas(?:e|ed|es|ing)|"
    r"increas(?:e|ed|es|ing)|enhanc(?:e|ed|es|ing)|restor(?:e|ed|es|ing)|"
    r"alleviat(?:e|ed|es|ing)|protect(?:s|ed|ive|ion)?|prevent(?:s|ed|ion)?|"
    r"promot(?:e|ed|es|ing)|accelerat(?:e|ed|es|ing)|inhibit(?:s|ed|ion)?|"
    r"efficacy|effective|significant(?:ly)?|no difference|not significant|"
    r"was associated|were associated|resulted in|showed|demonstrated)\b",
    re.IGNORECASE,
)
NON_RESULT_SECTION_RE = re.compile(
    r"^(?:BACKGROUND|OBJECTIVE|OBJECTIVES|AIM|AIMS|PURPOSE|METHOD|METHODS)\s*:",
    re.IGNORECASE,
)
NON_RESULT_INTENT_RE = re.compile(
    r"^(?:the\s+)?(?:objective|objectives|aim|aims|purpose)\b|"
    r"^this\s+(?:study|review)\s+(?:aimed|was designed|sought)\b|"
    r"\b(?:the aim|the purpose) of (?:this|the) (?:study|review)\b",
    re.IGNORECASE,
)
# A literal ``skin`` hit is not always dermatology. These phrases commonly
# describe food, packaging, or source material and must not create a cosmetic
# paper candidate.
NON_DERMATOLOGY_CONTEXT_RE = re.compile(
    r"\b(chicken skin|grape skin|fruit skin|fish skin|chicken breast freshness|"
    r"beef bologna|deli meat|food packaging|food spoilage|meat spoilage|"
    r"edible film|fruit freshness)\b",
    re.IGNORECASE,
)

# An exact ingredient mention can still be only one component of a formulation
# or a delivery material. Those mentions are not direct single-ingredient
# outcomes.
FORMULATION_LIMIT_RE = re.compile(
    r"\b(combination|combined|mixture|complex|compound|multi[- ]ingredient|"
    r"based on|"
    r"encapsulat(?:e|ed|ion)|conjugat(?:e|ed|ion)|graft(?:ed|ing)?|doped|"
    r"incorporat(?:e|ed|ion)|impregnat(?:e|ed|ion)|biofunctionalized|hybrid|"
    r"blend(?:ed)?|loaded|enriched|adjuvant|3[- ]in[- ]1|multi[- ]modal)\b|"
    r"\s\(and\)\s",
    re.IGNORECASE,
)
CONTEXTUAL_MENTION_RE = re.compile(
    r"\b(due to (?:its |their )?(?:bioactive )?(?:compounds?|constituents?)|"
    r"compounds? (?:such as|like)|ingredients? (?:such as|like)|"
    r"used as (?:a )?(?:vehicle|carrier|solvent|excipient|base)|"
    r"in petroleum jelly|dissolved in|delivery of)\b",
    re.IGNORECASE,
)
MECHANISM_CONTEXT_RE = re.compile(
    r"\b(transporter|water channel|receptor|knockout|gene expression|"
    r"signaling pathway|molecular pathway|biomarker|antimicrobial proteins?|"
    r"antimicrobial peptides?)\b",
    re.IGNORECASE,
)
TERM_PREFIX_LIMIT_RE = re.compile(
    r"\b(antimicrobial|signal|bacterial|carboxymethyl|hydroxypropyl|modified|"
    r"hydrolyzed|nano|palmitoyl|compound|poly|alpha|beta|gamma|α|β|γ|"
    r"sorbitan|probiotic|aspartyl)\s*[- ]*$",
    re.IGNORECASE,
)
TERM_SUFFIX_LIMIT_RE = re.compile(
    r"^\s*(?:amino acid\s+)?(precursor|precursors|derivative|derivatives|"
    r"conjugate|conjugates|complex|nanoparticle|nanoparticles|polyphenol|"
    r"polyphenols|catechin|catechins|phytochemical|extract|amide|"
    r"amide derivatives?|sulfate|phosphate)\b",
    re.IGNORECASE,
)
TERM_BIOMARKER_SUFFIX_RE = re.compile(
    r"^\s*(level|levels|content|concentration|concentrations|expression)\b",
    re.IGNORECASE,
)
ACTIVE_LIST_RE = re.compile(
    r"\b(?:actives?|ingredients?|components?)\s+(?:included|include|comprise|"
    r"comprised|were|are)\b",
    re.IGNORECASE,
)

NEW_EFFECT_PATTERNS: dict[str, re.Pattern[str]] = {
    "wound_healing": re.compile(r"\b(wound healing|burn healing|re-epithelialization)\b", re.I),
    "antimicrobial_skin": re.compile(
        r"\b(antimicrobial|antibacterial|antifungal|skin infection|biofilm)\b", re.I
    ),
    "photoprotection": re.compile(
        r"\b(photoprotection|photoprotective|uv protection|ultraviolet protection|sun protection)\b",
        re.I,
    ),
    "scar_care": re.compile(r"\b(scar|scarring|keloid)\b", re.I),
    "pore_appearance": re.compile(r"\b(pore size|facial pores|pore appearance)\b", re.I),
    "mattifying": re.compile(r"\b(mattifying|shine reduction|skin gloss)\b", re.I),
    "skin_microbiome": re.compile(r"\b(skin microbiome|skin microbiota|microbial diversity)\b", re.I),
}

MECHANISM_PATTERNS: dict[str, re.Pattern[str]] = {
    "antioxidant": re.compile(r"\b(antioxidant|oxidative stress|reactive oxygen species|ros)\b", re.I),
    "anti_inflammatory_mechanism": re.compile(
        r"\b(cytokine|nf-kappa ?b|cox-2|interleukin|tnf-alpha|inflammatory marker)\b",
        re.I,
    ),
    "collagen_mechanism": re.compile(r"\b(collagen synthesis|matrix metalloproteinase|mmp-?1)\b", re.I),
    "melanogenesis_mechanism": re.compile(r"\b(tyrosinase|melanogenesis)\b", re.I),
    "barrier_mechanism": re.compile(r"\b(ceramide synthesis|filaggrin|tight junction)\b", re.I),
}

SAFETY_RE = re.compile(
    r"\b(contact dermatitis|sensiti[sz](?:er|ers|ation|ing)?|allergen(?:ic|icity)?|"
    r"skin irritation|irritant|adverse (?:event|effect)|toxicity|toxic|phototoxic|"
    r"patch test|safety|comedogenic|acnegenic)\b",
    re.IGNORECASE,
)
NON_COSMETIC_APPLICATION_RE = re.compile(
    r"\b(feed additive|all animal species|pigeon lice|mosquito repellent|"
    r"food additive challenge|venous insufficiency|ankle sprain|"
    r"glucose sensors?|insulin pumps?|hair growth formulation|"
    r"anti-cancer drug|anticancer drug|pharmaceutical excipient|"
    r"melanoma cells?|oral supplementation|ocular surface|dry eye|corneal|"
    r"ophthalmic|conjunctivitis|microsurgery|bronchiectasis|mendelian randomization)\b",
    re.IGNORECASE,
)
EVIDENCE_ROLE_ORDER = (
    "direct_effect",
    "safety_evidence",
    "formulation_evidence",
    "mechanism_evidence",
    "reference_evidence",
)
EVIDENCE_ROLE_BONUS = {
    "direct_effect": 50,
    "safety_evidence": 40,
    "formulation_evidence": 20,
    "mechanism_evidence": 15,
    "reference_evidence": 10,
}
EVIDENCE_ROLE_SELECTION_LIMIT = {
    "direct_effect": 3,
    "safety_evidence": 1,
    "formulation_evidence": 1,
    "mechanism_evidence": 2,
    "reference_evidence": 1,
}

TARGET_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "search_terms",
    "search_query",
    "raw_pubmed_hit_count",
    "selected_paper_count",
    "catalog_status",
    "review_status",
    "score_change",
    "searched_on",
    "pipeline_version",
]

PAPER_FIELDS = [
    "ingredient_rank",
    "paper_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "paper_key",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "authors",
    "abstract",
    "evidence_tier",
    "evidence_kind",
    "relation_scope",
    "applicability",
    "evidence_roles",
    "selection_reason",
    "selection_score",
    "outcome_count",
    "review_status",
    "score_change",
]

SCREENING_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "paper_key",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "authors",
    "abstract",
    "evidence_tier",
    "evidence_kind",
    "relation_scope",
    "applicability",
    "evidence_roles",
    "selection_score",
    "selected_representative",
    "exclusion_reason",
    "review_status",
    "score_change",
]

OUTCOME_FIELDS = [
    "ingredient_rank",
    "paper_rank",
    "outcome_rank",
    "ingredient_id",
    "paper_key",
    "pmid",
    "evidence_span",
    "ingredient_outcome_relation",
    "mapping_status",
    "mapped_effect_ids",
    "new_effect_candidate",
    "mechanism_label",
    "direction",
    "direction_by_effect_json",
    "direction_conflict",
    "direction_policy_version",
    "evidence_tier",
    "relation_scope",
    "applicability",
    "review_status",
    "score_change",
]

NEW_EFFECT_SUMMARY_FIELDS = [
    "new_effect_candidate",
    "ingredient_count",
    "paper_count",
    "outcome_count",
    "best_evidence_tier",
    "candidate_strength",
    "sample_ingredients",
    "sample_spans_json",
    "review_status",
    "score_change",
]


class CatalogClient(Protocol):
    request_count: int
    retry_count: int

    def search(
        self,
        query: str,
        *,
        window_start: date,
        window_end: date,
        retmax: int,
        sort: str = "pub_date",
    ) -> list[str]: ...

    def fetch(self, pmids: Sequence[str]) -> dict[str, PaperMetadata]: ...


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def select_top_ingredients(
    role_rows: Sequence[Mapping[str, str]],
    *,
    target_count: int,
) -> list[dict[str, str]]:
    candidates = [row for row in role_rows if not row["ingredient_id"].startswith("ing_pending_")]
    candidates.sort(
        key=lambda row: (
            -int(row.get("product_count") or 0),
            str(row["ingredient_id"]),
        )
    )
    return [dict(row) for row in candidates[:target_count]]


def _usable_terms(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = normalize_phrase(value)
        if len(normalized) < 4 or normalized in AMBIGUOUS_SEARCH_TERMS:
            continue
        if value not in output:
            output.append(value)
    return output[:16]


def build_ingredient_skin_query(ingredient_terms: Sequence[str]) -> str:
    usable_terms = _usable_terms(ingredient_terms)
    if not usable_terms:
        return ""
    ingredient_clause = " OR ".join(pubmed_title_abstract_term(term) for term in usable_terms)
    skin_clause = " OR ".join(
        pubmed_title_abstract_term(term) for term in EXPANDED_SKIN_CONTEXT_TERMS
    )
    return f"({ingredient_clause}) AND ({skin_clause})"


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    normalized_text = f" {normalize_phrase(text)} "
    return any(
        normalized_term and f" {normalized_term} " in normalized_text
        for term in terms
        if (normalized_term := normalize_phrase(term))
    )


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\s+(?=[A-Z]+:)", text or "")
        if sentence.strip()
    ]


def _mapped_effects(sentence: str) -> list[str]:
    return match_effect_ids(sentence)


def _first_pattern_label(
    sentence: str,
    patterns: Mapping[str, re.Pattern[str]],
) -> str:
    return next((label for label, pattern in patterns.items() if pattern.search(sentence)), "")


def _term_occurrences(sentence: str, ingredient_terms: Sequence[str]) -> list[tuple[int, int]]:
    occurrences: list[tuple[int, int]] = []
    for term in _usable_terms(ingredient_terms):
        pattern = re.escape(term).replace(r"\ ", r"\s+")
        occurrences.extend(match.span() for match in re.finditer(pattern, sentence, re.I))
    longest_first = sorted(set(occurrences), key=lambda span: (span[0], -(span[1] - span[0])))
    output: list[tuple[int, int]] = []
    for span in longest_first:
        if any(start <= span[0] and span[1] <= end for start, end in output):
            continue
        output.append(span)
    return sorted(output)


def _term_form_is_limited(sentence: str, ingredient_terms: Sequence[str]) -> bool:
    for start, end in _term_occurrences(sentence, ingredient_terms):
        before = sentence[max(0, start - 40) : start]
        after = sentence[end : end + 50]
        if TERM_PREFIX_LIMIT_RE.search(before) or TERM_SUFFIX_LIMIT_RE.search(after):
            return True
        if re.match(r"\s*[-/]\s*\w", after) or re.search(
            r"\w\s*[-/]\s*$", before
        ):
            return True
        if re.search(r",\s*$", before) and re.match(r"\s*,", after):
            return True
    return False


def _term_is_measured_biomarker(sentence: str, ingredient_terms: Sequence[str]) -> bool:
    return any(
        TERM_BIOMARKER_SUFFIX_RE.search(sentence[end : end + 40])
        for _, end in _term_occurrences(sentence, ingredient_terms)
    )


def _ingredient_is_result_subject(sentence: str, ingredient_terms: Sequence[str]) -> bool:
    result_spans = [match.span() for match in RESULT_RE.finditer(sentence)]
    for term_start, term_end in _term_occurrences(sentence, ingredient_terms):
        for result_start, result_end in result_spans:
            if term_end <= result_start and result_start - term_end <= 160:
                bridge = sentence[term_end:result_start]
                if ";" not in bridge:
                    return True
            if result_end <= term_start and term_start - result_end <= 100:
                bridge = sentence[result_end:term_start]
                if re.search(r"\b(by|with|after|following|using|through)\b", bridge, re.I):
                    return True
        before = sentence[max(0, term_start - 60) : term_start]
        if re.search(
            r"\b(topical|topically|treatment with|treated with|application of|"
            r"administration of|exposure to|use of)\s*$",
            before,
            re.I,
        ):
            return True
    return False


def _ingredient_outcome_relation(
    sentence: str,
    *,
    paper: PaperMetadata,
    assessment: PaperAssessment,
    ingredient_terms: Sequence[str],
) -> str:
    paper_text = f"{paper.title} {sentence}"
    if NON_DERMATOLOGY_CONTEXT_RE.search(paper_text):
        return "irrelevant_context"
    if (
        FORMULATION_LIMIT_RE.search(paper_text)
        or ACTIVE_LIST_RE.search(sentence)
        or _term_form_is_limited(sentence, ingredient_terms)
    ):
        return "formulation_limited"
    if CONTEXTUAL_MENTION_RE.search(sentence):
        return "contextual_mention"
    if _term_is_measured_biomarker(sentence, ingredient_terms):
        return "contextual_mention"
    if MECHANISM_CONTEXT_RE.search(sentence):
        return "mechanism_context"
    if not _ingredient_is_result_subject(sentence, ingredient_terms):
        return "contextual_mention"
    if assessment.evidence_tier == 8:
        return "review_summary"
    return "direct"


def extract_outcomes(
    paper: PaperMetadata,
    assessment: PaperAssessment,
    ingredient_terms: Sequence[str],
) -> list[dict[str, str]]:
    # Mixed-method papers can contain both cell experiments and a human trial.
    # Do not downgrade the human result sentences merely because an in-vitro
    # section appears elsewhere in the same abstract.
    paper_is_mechanistic = assessment.applicability == "mechanistic"
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for sentence in [paper.title, *_sentences(paper.abstract)]:
        normalized = normalize_phrase(sentence)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if NON_RESULT_SECTION_RE.search(sentence) or NON_RESULT_INTENT_RE.search(sentence):
            continue
        if not RESULT_RE.search(sentence):
            continue
        if not _contains_any(sentence, EXPANDED_SKIN_CONTEXT_TERMS):
            continue
        if not _contains_any(sentence, ingredient_terms):
            continue

        ingredient_relation = _ingredient_outcome_relation(
            sentence,
            paper=paper,
            assessment=assessment,
            ingredient_terms=ingredient_terms,
        )
        mapped = _mapped_effects(sentence)
        direction_assessments = assess_outcome_directions(sentence)
        direction, direction_conflict, direction_json = summarize_direction_assessments(
            direction_assessments,
            fallback_text=sentence,
        )
        new_effect = _first_pattern_label(sentence, NEW_EFFECT_PATTERNS)
        mechanism = _first_pattern_label(sentence, MECHANISM_PATTERNS)
        if ingredient_relation in {
            "irrelevant_context",
            "formulation_limited",
            "contextual_mention",
        }:
            status = "unclear"
            new_effect = ""
        elif ingredient_relation == "mechanism_context":
            status = "mechanism_only" if mapped or mechanism else "unclear"
            new_effect = ""
        elif new_effect:
            status = "new_effect_candidate"
        elif mapped and paper_is_mechanistic:
            status = "mechanism_only"
        elif mapped:
            status = "mapped_existing_effect"
        elif mechanism:
            status = "mechanism_only"
        else:
            status = "unclear"
        output.append(
            {
                "evidence_span": sentence,
                "ingredient_outcome_relation": ingredient_relation,
                "mapping_status": status,
                "mapped_effect_ids": "|".join(mapped),
                "new_effect_candidate": new_effect,
                "mechanism_label": mechanism,
                "direction": direction,
                "direction_by_effect_json": direction_json,
                "direction_conflict": "Y" if direction_conflict else "N",
                "direction_policy_version": DIRECTION_POLICY_VERSION,
            }
        )
    return output[:20]


def _paper_evidence_roles(
    paper: PaperMetadata,
    assessment: PaperAssessment,
    outcomes: Sequence[Mapping[str, str]],
    ingredient_terms: Sequence[str],
) -> tuple[str, ...]:
    if assessment.relation_scope == "unconfirmed" or assessment.applicability == "route_mismatch":
        return ()
    text = f"{paper.title} {paper.abstract}"
    if NON_DERMATOLOGY_CONTEXT_RE.search(text) or NON_COSMETIC_APPLICATION_RE.search(text):
        return ()
    title_form_limited = (
        assessment.relation_scope == "title_exact"
        and _term_form_is_limited(paper.title, ingredient_terms)
    )

    roles: set[str] = set()
    if (
        assessment.applicability != "combination_or_formulation"
        and not title_form_limited
        and (
            assessment.relation_scope == "title_exact"
            or assessment.evidence_tier <= 4
        )
        and any(
        row["mapping_status"] in {"mapped_existing_effect", "new_effect_candidate"}
        and row["ingredient_outcome_relation"] in {"direct", "review_summary"}
        for row in outcomes
        )
    ):
        roles.add("direct_effect")
    safety_sentences = [paper.title, *_sentences(paper.abstract)]
    if (
        assessment.relation_scope == "title_exact"
        and not title_form_limited
        and not FORMULATION_LIMIT_RE.search(paper.title)
        and any(
        SAFETY_RE.search(sentence)
        and _contains_any(sentence, ingredient_terms)
        and _contains_any(sentence, EXPANDED_SKIN_CONTEXT_TERMS)
        and not NON_DERMATOLOGY_CONTEXT_RE.search(sentence)
        for sentence in safety_sentences
        )
    ):
        roles.add("safety_evidence")
    if (
        assessment.evidence_tier <= 4
        and assessment.relation_scope == "title_exact"
        and assessment.applicability == "combination_or_formulation"
        and _contains_any(text, EXPANDED_SKIN_CONTEXT_TERMS)
    ):
        roles.add("formulation_evidence")
    if (
        assessment.relation_scope == "title_exact"
        and not title_form_limited
        and assessment.applicability == "mechanistic"
        and (
        any(row["mapping_status"] == "mechanism_only" for row in outcomes)
        or (
            assessment.evidence_tier in {5, 6, 7}
        and any(
            row["ingredient_outcome_relation"] in {"direct", "mechanism_context"}
            for row in outcomes
        )
        )
        )
    ):
        roles.add("mechanism_evidence")
    if (
        assessment.evidence_tier == 8
        and assessment.relation_scope == "title_exact"
        and not title_form_limited
        and assessment.applicability == "reference_only"
        and any(row["mapping_status"] != "unclear" for row in outcomes)
    ):
        roles.add("reference_evidence")
    return tuple(role for role in EVIDENCE_ROLE_ORDER if role in roles)


def _paper_exclusion_reason(
    paper: PaperMetadata,
    assessment: PaperAssessment,
    roles: Sequence[str],
) -> str:
    if roles:
        return ""
    if assessment.relation_scope == "unconfirmed":
        return "ingredient_not_confirmed_in_title_or_abstract"
    if assessment.applicability == "route_mismatch":
        return "route_mismatch"
    if NON_DERMATOLOGY_CONTEXT_RE.search(f"{paper.title} {paper.abstract}"):
        return "non_dermatology_context"
    if NON_COSMETIC_APPLICATION_RE.search(f"{paper.title} {paper.abstract}"):
        return "non_cosmetic_application"
    return "no_useful_skin_evidence_role"


def _paper_selection_score(
    assessment: PaperAssessment,
    outcomes: Sequence[Mapping[str, str]],
    roles: Sequence[str],
) -> int:
    score = assessment.signal_score + max(
        (EVIDENCE_ROLE_BONUS[role] for role in roles),
        default=0,
    )
    if assessment.relation_scope == "title_exact":
        score += 10
    if "direct_effect" in roles:
        score += min(10, sum(row["mapping_status"] != "unclear" for row in outcomes) * 2)
    if "formulation_evidence" in roles and "direct_effect" not in roles:
        score -= 5
    return score


def _select_representatives(
    candidates: Sequence[
        tuple[
            PaperMetadata,
            PaperAssessment,
            list[dict[str, str]],
            tuple[str, ...],
            int,
        ]
    ],
    *,
    max_papers: int,
) -> list[
    tuple[
        PaperMetadata,
        PaperAssessment,
        list[dict[str, str]],
        tuple[str, ...],
        int,
    ]
]:
    selected = []
    role_counts: Counter[str] = Counter()
    for candidate in candidates:
        primary_role = candidate[3][0]
        if role_counts[primary_role] >= EVIDENCE_ROLE_SELECTION_LIMIT[primary_role]:
            continue
        selected.append(candidate)
        role_counts[primary_role] += 1
        if len(selected) >= max_papers:
            break
    return selected


def build_catalog(
    *,
    ingredient_rows: Sequence[Mapping[str, str]],
    ingredient_terms: Mapping[str, Sequence[str]],
    client: CatalogClient,
    as_of: date,
    retmax_per_ingredient: int,
    max_papers_per_ingredient: int,
    progress: Callable[[int, int, Mapping[str, str], int], None] | None = None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    queries: dict[str, str] = {}
    raw_pmids: dict[str, list[str]] = {}
    all_pmids: set[str] = set()
    for index, ingredient in enumerate(ingredient_rows, start=1):
        ingredient_id = ingredient["ingredient_id"]
        query = build_ingredient_skin_query(ingredient_terms[ingredient_id])
        queries[ingredient_id] = query
        if query:
            pmids = client.search(
                query,
                window_start=ALL_HISTORY_START,
                window_end=as_of,
                retmax=retmax_per_ingredient,
                sort="relevance",
            )
        else:
            pmids = []
        raw_pmids[ingredient_id] = pmids
        all_pmids.update(pmids)
        if progress:
            progress(index, len(ingredient_rows), ingredient, len(pmids))

    papers = client.fetch(sorted(all_pmids, key=int)) if all_pmids else {}
    target_output: list[dict[str, object]] = []
    paper_output: list[dict[str, object]] = []
    outcome_output: list[dict[str, object]] = []
    screening_output: list[dict[str, object]] = []

    for ingredient_rank, ingredient in enumerate(ingredient_rows, start=1):
        ingredient_id = ingredient["ingredient_id"]
        terms = ingredient_terms[ingredient_id]
        candidates: list[
            tuple[
                PaperMetadata,
                PaperAssessment,
                list[dict[str, str]],
                tuple[str, ...],
                int,
            ]
        ] = []
        screened: list[
            tuple[
                PaperMetadata,
                PaperAssessment,
                list[dict[str, str]],
                tuple[str, ...],
                int,
                str,
            ]
        ] = []
        for pmid in raw_pmids[ingredient_id]:
            paper = papers.get(pmid)
            if paper is None:
                continue
            assessment = assess_paper_candidate(paper, terms)
            outcomes = extract_outcomes(paper, assessment, terms)
            roles = _paper_evidence_roles(paper, assessment, outcomes, terms)
            score = _paper_selection_score(assessment, outcomes, roles)
            exclusion_reason = _paper_exclusion_reason(paper, assessment, roles)
            screened.append((paper, assessment, outcomes, roles, score, exclusion_reason))
            if roles:
                candidates.append((paper, assessment, outcomes, roles, score))
        candidates.sort(
            key=lambda item: (
                -item[4],
                item[1].evidence_tier,
                0 if item[1].relation_scope == "title_exact" else 1,
                item[0].pmid,
            )
        )
        selected = _select_representatives(
            candidates,
            max_papers=max_papers_per_ingredient,
        )
        selected_pmids = {paper.pmid for paper, *_ in selected}
        for paper, assessment, _, roles, score, exclusion_reason in screened:
            screening_output.append(
                {
                    "ingredient_rank": ingredient_rank,
                    "ingredient_id": ingredient_id,
                    "paper_key": f"PMID:{paper.pmid}",
                    "pmid": paper.pmid,
                    "doi": paper.doi,
                    "title": paper.title,
                    "journal": paper.journal,
                    "publication_date": paper.publication_date,
                    "publication_types": "; ".join(paper.publication_types),
                    "authors": "; ".join(paper.authors),
                    "abstract": paper.abstract,
                    "evidence_tier": assessment.evidence_tier,
                    "evidence_kind": assessment.evidence_kind,
                    "relation_scope": assessment.relation_scope,
                    "applicability": assessment.applicability,
                    "evidence_roles": "|".join(roles),
                    "selection_score": score,
                    "selected_representative": "Y" if paper.pmid in selected_pmids else "N",
                    "exclusion_reason": exclusion_reason,
                    "review_status": "candidate_unverified" if roles else "screened_out",
                    "score_change": "none",
                }
            )
        status = "papers_selected" if selected else (
            "ambiguous_search_name"
            if not queries[ingredient_id]
            else "no_pubmed_hit"
            if not raw_pmids[ingredient_id]
            else "no_useful_paper_found"
        )
        target_output.append(
            {
                "ingredient_rank": ingredient_rank,
                "ingredient_id": ingredient_id,
                "name_ko": ingredient.get("name_ko", ""),
                "name_en": ingredient.get("name_en", ""),
                "product_count": ingredient.get("product_count", "0"),
                "search_terms": "|".join(_usable_terms(terms)),
                "search_query": queries[ingredient_id],
                "raw_pubmed_hit_count": len(raw_pmids[ingredient_id]),
                "selected_paper_count": len(selected),
                "catalog_status": status,
                "review_status": "candidate_unverified" if selected else "not_found",
                "score_change": "none",
                "searched_on": as_of.isoformat(),
                "pipeline_version": PIPELINE_VERSION,
            }
        )

        for paper_rank, (paper, assessment, outcomes, roles, selection_score) in enumerate(
            selected,
            start=1,
        ):
            paper_key = f"PMID:{paper.pmid}"
            paper_output.append(
                {
                    "ingredient_rank": ingredient_rank,
                    "paper_rank": paper_rank,
                    "ingredient_id": ingredient_id,
                    "name_ko": ingredient.get("name_ko", ""),
                    "name_en": ingredient.get("name_en", ""),
                    "product_count": ingredient.get("product_count", "0"),
                    "paper_key": paper_key,
                    "pmid": paper.pmid,
                    "doi": paper.doi,
                    "title": paper.title,
                    "journal": paper.journal,
                    "publication_date": paper.publication_date,
                    "publication_types": "; ".join(paper.publication_types),
                    "authors": "; ".join(paper.authors),
                    "abstract": paper.abstract,
                    "evidence_tier": assessment.evidence_tier,
                    "evidence_kind": assessment.evidence_kind,
                    "relation_scope": assessment.relation_scope,
                    "applicability": assessment.applicability,
                    "evidence_roles": "|".join(roles),
                    "selection_reason": roles[0],
                    "selection_score": selection_score,
                    "outcome_count": len(outcomes),
                    "review_status": "candidate_unverified",
                    "score_change": "none",
                }
            )
            for outcome_rank, outcome in enumerate(outcomes, start=1):
                outcome_output.append(
                    {
                        "ingredient_rank": ingredient_rank,
                        "paper_rank": paper_rank,
                        "outcome_rank": outcome_rank,
                        "ingredient_id": ingredient_id,
                        "paper_key": paper_key,
                        "pmid": paper.pmid,
                        **outcome,
                        "evidence_tier": assessment.evidence_tier,
                        "relation_scope": assessment.relation_scope,
                        "applicability": assessment.applicability,
                        "review_status": "candidate_unverified",
                        "score_change": "none",
                    }
                )

    summary_output = summarize_new_effects(outcome_output)
    return target_output, paper_output, outcome_output, summary_output, screening_output


def summarize_new_effects(
    outcome_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in outcome_rows:
        if row["mapping_status"] != "new_effect_candidate" or row[
            "ingredient_outcome_relation"
        ] not in {"direct", "review_summary"}:
            continue
        grouped[str(row["new_effect_candidate"])].append(row)

    output: list[dict[str, object]] = []
    for label, rows in grouped.items():
        ingredients = sorted({str(row["ingredient_id"]) for row in rows})
        papers = sorted({str(row["paper_key"]) for row in rows})
        best_tier = min(int(row["evidence_tier"]) for row in rows)
        output.append(
            {
                "new_effect_candidate": label,
                "ingredient_count": len(ingredients),
                "paper_count": len(papers),
                "outcome_count": len(rows),
                "best_evidence_tier": best_tier,
                "candidate_strength": (
                    "human_outcome_candidate"
                    if best_tier <= 4
                    else "preclinical_outcome_candidate"
                    if best_tier <= 7
                    else "reference_signal_only"
                ),
                "sample_ingredients": "|".join(ingredients[:10]),
                "sample_spans_json": json.dumps(
                    [str(row["evidence_span"]) for row in rows[:5]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "review_status": "candidate_unverified",
                "score_change": "none",
            }
        )
    output.sort(
        key=lambda row: (
            -int(row["ingredient_count"]),
            -int(row["paper_count"]),
            str(row["new_effect_candidate"]),
        )
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--roles",
        type=Path,
        default=Path("data/reconciliation/ingredient_role_review.csv"),
    )
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument(
        "--max-papers-per-ingredient",
        type=int,
        default=DEFAULT_MAX_PAPERS_PER_INGREDIENT,
    )
    parser.add_argument(
        "--retmax-per-ingredient",
        type=int,
        default=DEFAULT_RETMAX_PER_INGREDIENT,
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""))
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    parser.add_argument(
        "--targets-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_500.csv"),
    )
    parser.add_argument(
        "--papers-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_candidates_500.csv"),
    )
    parser.add_argument(
        "--outcomes-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_outcomes_500.csv"),
    )
    parser.add_argument(
        "--new-effects-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_new_effect_candidates.csv"),
    )
    parser.add_argument(
        "--screening-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_screening_all_500.csv"),
    )
    args = parser.parse_args()

    ingredients = select_top_ingredients(read_csv(args.roles), target_count=args.target_count)
    ingredient_ids = {row["ingredient_id"] for row in ingredients}
    terms = load_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        ingredient_ids,
    )
    client = PubMedClient(
        email=args.email,
        api_key=args.api_key,
        tool=DEFAULT_TOOL_NAME,
        request_delay_seconds=args.request_delay,
    )

    def progress(
        index: int,
        total: int,
        ingredient: Mapping[str, str],
        hit_count: int,
    ) -> None:
        if index == 1 or index % 25 == 0 or index == total:
            print(
                f"Ingredient-first PubMed {index}/{total}: "
                f"{ingredient['ingredient_id']} raw_hits={hit_count}",
                flush=True,
            )

    targets, papers, outcomes, new_effects, screening = build_catalog(
        ingredient_rows=ingredients,
        ingredient_terms=terms,
        client=client,
        as_of=args.as_of,
        retmax_per_ingredient=args.retmax_per_ingredient,
        max_papers_per_ingredient=args.max_papers_per_ingredient,
        progress=progress,
    )
    write_csv(args.targets_output, TARGET_FIELDS, targets)
    write_csv(args.papers_output, PAPER_FIELDS, papers)
    write_csv(args.outcomes_output, OUTCOME_FIELDS, outcomes)
    write_csv(args.new_effects_output, NEW_EFFECT_SUMMARY_FIELDS, new_effects)
    write_csv(args.screening_output, SCREENING_FIELDS, screening)
    print(
        "Ingredient-first catalog complete: "
        f"ingredients={len(targets)} papers={len(papers)} outcomes={len(outcomes)} "
        f"screened={len(screening)} new_effect_labels={len(new_effects)} "
        f"requests={client.request_count} "
        f"retries={client.retry_count}"
    )


if __name__ == "__main__":
    main()
