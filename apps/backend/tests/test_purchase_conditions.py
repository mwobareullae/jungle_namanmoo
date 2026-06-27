from app.services.purchase_conditions import build_brand_aliases, parse_purchase_conditions


def test_parse_purchase_conditions_matches_category_brand_and_price() -> None:
    result = parse_purchase_conditions(
        "속건조가 있는데 라운드랩 앰플 2만원 이하로 추천해줘",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    assert [category.category_code for category in result.categories] == ["serum"]
    assert [brand.brand_code for brand in result.brands] == ["라운드랩"]
    assert result.price_min is None
    assert result.price_max == 20000
    assert result.price_text == "2만원 이하"
    assert result.price_max_text == "2만원 이하"


def test_parse_purchase_conditions_deduplicates_category_aliases() -> None:
    result = parse_purchase_conditions("스킨이나 토너 중에서 30000원 미만")

    assert [category.category_code for category in result.categories] == ["toner"]
    assert result.price_min is None
    assert result.price_max == 29999


def test_parse_purchase_conditions_matches_price_range_as_hard_filter() -> None:
    result = parse_purchase_conditions("스킨푸드 세럼 2만원대 추천")

    assert [category.category_code for category in result.categories] == ["serum"]
    assert result.price_min == 20000
    assert result.price_max == 29999
    assert result.price_text == "2만원대"


def test_parse_purchase_conditions_maps_common_serum_typos_to_serum() -> None:
    result = parse_purchase_conditions("속건조 새럼 엠플 추천")

    assert [category.category_code for category in result.categories] == ["serum"]
    assert result.categories[0].name == "세럼"


def test_parse_purchase_conditions_matches_attached_category_suffixes() -> None:
    cases = (
        ("진정앰플 추천", "serum"),
        ("미백세럼 추천", "serum"),
        ("닦토토너 추천", "toner"),
        ("장벽 에멀젼 추천", "lotion"),
        ("속건조 수분크림 추천", "cream"),
    )

    for text, category_code in cases:
        result = parse_purchase_conditions(text)

        assert [category.category_code for category in result.categories] == [category_code]


def test_parse_purchase_conditions_does_not_match_skin_inside_brand_only_query() -> None:
    result = parse_purchase_conditions(
        "스킨푸드 추천",
        brand_aliases=build_brand_aliases(("스킨푸드",)),
    )

    assert [brand.name for brand in result.brands] == ["스킨푸드"]
    assert result.categories == ()


def test_parse_purchase_conditions_matches_compact_and_english_brand_aliases() -> None:
    result = parse_purchase_conditions(
        "ROUND LAB 세럼 추천",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    assert [brand.name for brand in result.brands] == ["라운드랩"]
    assert [category.category_code for category in result.categories] == ["serum"]


def test_parse_purchase_conditions_uses_strict_boundaries() -> None:
    result = parse_purchase_conditions(
        "스킨푸드 세럼 추천",
        brand_aliases=build_brand_aliases(("스킨푸드",)),
    )

    assert [brand.name for brand in result.brands] == ["스킨푸드"]
    assert [category.category_code for category in result.categories] == ["serum"]
    assert result.price_max is None


def test_parse_purchase_conditions_can_match_data_driven_brand_names() -> None:
    result = parse_purchase_conditions(
        "에스트라 토너 추천",
        brand_aliases=build_brand_aliases(("에스트라",)),
    )

    assert [brand.brand_code for brand in result.brands] == ["에스트라"]
    assert [category.category_code for category in result.categories] == ["toner"]


def test_parse_purchase_conditions_returns_empty_result_without_constraints() -> None:
    result = parse_purchase_conditions("속건조랑 모공이 고민이야")

    assert result.categories == ()
    assert result.brands == ()
    assert result.price_min is None
    assert result.price_max is None
    assert result.price_text is None
    assert result.price_max_text is None
