# Ingredient score eligibility review

Generated: 2026-07-13

## Question

Can the 180 ingredients with representative PubMed candidates, and the 190
ingredients with raw PubMed hits but no representative candidate, be used in
ingredient scoring?

## Result

No row changes runtime scoring now. Every result remains
`candidate_unverified` and `runtime_score_change=none`.

| Cohort | Decision | Ingredients |
| --- | --- | ---: |
| representative 180 | Positive benefit review candidate | 2 |
| representative 180 | Clear risk-penalty review candidate | 11 |
| representative 180 | Mechanism support only | 11 |
| representative 180 | New effect-axis review | 12 |
| representative 180 | Formulation only | 18 |
| representative 180 | General safety signal only | 116 |
| representative 180 | Uncertain effect only | 1 |
| representative 180 | Reference only | 3 |
| representative 180 | Not scoreable from current hits | 6 |
| raw-hit 190 | Mechanism support only | 1 |
| raw-hit 190 | Not scoreable from current hits | 189 |

The two positive benefit candidates are:

- `ectoin` x `effect_calming`, PMID 37792331
- `licorice_extract` x `effect_calming`, PMID 14522625

Both are human topical studies in medical dermatitis contexts, so they are
review candidates rather than automatic cosmetic scores. Glutathione PMID
30895708 was not retained as a positive wrinkle candidate because the review
describes only a trend and concludes that the evidence is inconclusive.

The 11 risk candidates have clear human-topical adverse titles such as contact
dermatitis, contact allergy, sensitization, or irritation. A paper that merely
mentions safety does not become a risk score.

## Files

- `ingredient_score_eligibility_370.csv`: one decision per ingredient
- `ingredient_score_claim_candidates.csv`: paper and outcome audit rows
- `ingredient_score_eligibility_summary.json`: cohort totals
- `../scripts/assess_ingredient_score_eligibility.py`: deterministic review code
- `../scripts/tests/test_assess_ingredient_score_eligibility.py`: policy tests

## Verification

- Data-script tests: 75 passed
- Eligibility policy tests: 10 passed
- 370 unique ingredients: 180 representative + 190 raw-hit
- Runtime seed hashes unchanged
- `git diff --check`: passed
