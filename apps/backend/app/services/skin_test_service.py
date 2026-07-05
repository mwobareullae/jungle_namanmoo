from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.skin import (
    BaumannTypeProfile,
    SkinProfile,
    SkinTestAnswer,
    SkinTestOption,
    SkinTestQuestion,
    SkinTestResult,
    SkinTestVersion,
)
from app.schemas.profile import SkinProfileResponse
from app.schemas.skin_test import (
    SkinTestAnswerInput,
    SkinTestOptionResponse,
    SkinTestQuestionResponse,
    SkinTestQuestionsResponse,
    SkinTestResultData,
    SkinTestSubmitRequest,
)
from app.services.skin_profile_service import (
    BAUMANN_SIGNAL_WEIGHT,
    SkinServiceError,
    load_skin_profile_for_user,
    to_skin_profile_data,
)


DEFAULT_VERSION_CODE = "baumann_8q_v1"
DEFAULT_SCORING_VERSION = "baumann_score_v1"
AXIS_PAIRS = {
    "OD": ("O", "D"),
    "SR": ("S", "R"),
    "PN": ("P", "N"),
    "WT": ("W", "T"),
}


@dataclass(frozen=True)
class _OptionSeed:
    option_key: str
    label: str
    internal_label: str | None
    axis_value: str | None
    score_delta: dict[str, int]
    commerce_mapping: dict | None = None


@dataclass(frozen=True)
class _QuestionSeed:
    question_key: str
    sequence: int
    axis: str
    question_text: str
    options: tuple[_OptionSeed, ...]
    helper_text: str | None = None


@dataclass(frozen=True)
class _BaumannProfileSeed:
    type_code: str
    object_name: str
    title: str
    subtitle: str
    concern_tags: tuple[str, ...]
    keywords: tuple[str, ...]


QUESTION_SEEDS: tuple[_QuestionSeed, ...] = (
    _QuestionSeed(
        "Q1",
        1,
        "OD",
        "세안 후 아무것도 바르지 않고 몇 시간 지난 오후, 내 피부는?",
        (
            _OptionSeed("A", "얼굴 전체가 번들거려 기름종이나 파우더가 필요하다.", "O. 극지성", "O", {"O": 2}),
            _OptionSeed("B", "T존은 번들거리지만 볼은 적당하거나 살짝 건조하다.", "O. 약지성", "O", {"O": 1}),
            _OptionSeed("C", "크게 당기진 않지만 만지면 살짝 까끌하고 푸석하다.", "D. 약건성", "D", {"D": 1}),
            _OptionSeed("D", "속당김이 심하고 각질이 일어나며 갈라지는 느낌이다.", "D. 극건성", "D", {"D": 2}),
        ),
    ),
    _QuestionSeed(
        "Q2",
        2,
        "SR",
        "후기는 좋지만 자극이 있을 수 있는 화장품을 처음 발랐을 때, 내 피부는?",
        (
            _OptionSeed("A", "바르자마자 피부가 따갑고 붉어진다.", "S. 극민감", "S", {"S": 2}),
            _OptionSeed("B", "조금만 안 맞아도 쉽게 뒤집어진다.", "S. 약민감", "S", {"S": 1}),
            _OptionSeed("C", "가끔 따갑거나 붉어질 때가 있다.", "R. 약저항", "R", {"R": 1}),
            _OptionSeed("D", "대부분 문제없이 잘 맞는다.", "R. 극저항", "R", {"R": 2}),
        ),
    ),
    _QuestionSeed(
        "Q3",
        3,
        "CATEGORY_PREF",
        "지금 내 피부에 제일 필요한 제품은?",
        (
            _OptionSeed(
                "A",
                "피부를 진정시키고 결을 정돈하는 토너·패드.",
                "진정·데일리 케어 선호",
                None,
                {},
                {"category_preference": {"code": "toner_pad", "label": "진정·데일리 케어 선호"}},
            ),
            _OptionSeed(
                "B",
                "고민을 집중 관리해줄 앰플·세럼·에센스.",
                "고기능성 제품 선호",
                None,
                {},
                {"category_preference": {"code": "ampoule_serum_essence", "label": "고기능성 제품 선호"}},
            ),
            _OptionSeed(
                "C",
                "속부터 든든하게 채워주는 로션·크림.",
                "보습·장벽 케어 선호",
                None,
                {},
                {"category_preference": {"code": "lotion_cream", "label": "보습·장벽 케어 선호"}},
            ),
            _OptionSeed(
                "D",
                "자외선과 노화를 미리 막는 선크림.",
                "예방·안티에이징 관심",
                None,
                {},
                {"category_preference": {"code": "suncare", "label": "예방·안티에이징 관심"}},
            ),
        ),
    ),
    _QuestionSeed(
        "Q4",
        4,
        "PN",
        "얼굴에 트러블이 올라왔다 가라앉은 뒤, 그 자리는?",
        (
            _OptionSeed("A", "갈색·짙은 자국으로 남아 몇 달이 지나도 잘 안 없어진다.", "P. 극색소", "P", {"P": 2}),
            _OptionSeed("B", "붉다가 갈색 자국이 되고, 옅어지기까지 오래 걸린다.", "P. 약색소", "P", {"P": 1}),
            _OptionSeed("C", "붉은 기가 잠깐 돌다가 몇 주 안에 흔적 없이 사라진다.", "N. 약비색소", "N", {"N": 1}),
            _OptionSeed("D", "자국이 거의 안 남고 며칠이면 깨끗해진다.", "N. 극비색소", "N", {"N": 2}),
        ),
    ),
    _QuestionSeed(
        "Q5",
        5,
        "BUYING_CRITERIA",
        "새 화장품을 앞에 두고, 나도 모르게 제일 먼저 확인하는 건?",
        (
            _OptionSeed(
                "A",
                "성분표부터 꼼꼼히 훑어본다.",
                "성분 중심",
                None,
                {},
                {"buying_criteria": {"code": "ingredient", "label": "성분 중심"}},
            ),
            _OptionSeed(
                "B",
                "나랑 비슷한 피부인 사람들의 후기가 궁금하다.",
                "후기 중심",
                None,
                {},
                {"buying_criteria": {"code": "review", "label": "후기 중심"}},
            ),
            _OptionSeed(
                "C",
                "용량 대비 가격이 괜찮은지 따져본다.",
                "가성비 중심",
                None,
                {},
                {"buying_criteria": {"code": "value", "label": "가성비 중심"}},
            ),
            _OptionSeed(
                "D",
                "어느 브랜드에서 나온 건지부터 눈에 들어온다.",
                "브랜드 중심",
                None,
                {},
                {"buying_criteria": {"code": "brand", "label": "브랜드 중심"}},
            ),
        ),
    ),
    _QuestionSeed(
        "Q6",
        6,
        "WT",
        "손가락으로 볼을 살짝 눌렀다 뗐을 때, 내 피부는?",
        (
            _OptionSeed("A", "눌린 자국이 오래 남고, 눈가나 입가의 잔주름이 신경쓰인다.", "극주름", "W", {"W": 2}),
            _OptionSeed("B", "자국이 잠깐 남고 미세한 잔주름이 보이기 시작한다.", "약주름", "W", {"W": 1}),
            _OptionSeed("C", "금세 원래대로 돌아오고 탄력도 무난한 편이다.", "약탄력", "T", {"T": 1}),
            _OptionSeed("D", "누르는 순간 바로 튕겨 올라온다.", "극탄력", "T", {"T": 2}),
        ),
    ),
    _QuestionSeed(
        "Q7",
        7,
        "PRICE_PREF",
        "내 화장대에 오래 살아남는 제품은 보통 어느 쪽?",
        (
            _OptionSeed(
                "A",
                "매일 손이 가는 편안한 데일리 제품.",
                "합리적 가격·반복 구매형",
                None,
                {},
                {"price_investment": {"code": "daily_repeat_value", "label": "합리적 가격·반복 구매형"}},
            ),
            _OptionSeed(
                "B",
                "성분이 좋아 믿고 계속 쓰는 제품.",
                "기능성 투자형",
                None,
                {},
                {"price_investment": {"code": "functional_investment", "label": "기능성 투자형"}},
            ),
            _OptionSeed(
                "C",
                "용량이 넉넉해 아낌없이 쓰는 제품.",
                "가성비·용량 중시형",
                None,
                {},
                {"price_investment": {"code": "value_volume", "label": "가성비·용량 중시형"}},
            ),
            _OptionSeed(
                "D",
                "한 번 써보고 효과가 느껴져 계속 찾게 되는 제품.",
                "프리미엄·효능 중시형",
                None,
                {},
                {"price_investment": {"code": "premium_effect", "label": "프리미엄·효능 중시형"}},
            ),
        ),
    ),
    _QuestionSeed(
        "Q8",
        8,
        "TRIGGER_PREF",
        "마음에 든 제품이 있을 때, 결국 나를 결심하게 만드는 결정적 한 방은?",
        (
            _OptionSeed(
                "A",
                '"2주 만에 개선" 같은 임상 수치와 근거.',
                "성분·효과형",
                None,
                {},
                {"decision_trigger": {"code": "clinical_evidence", "label": "성분·효과형"}},
            ),
            _OptionSeed(
                "B",
                "내 피부와 비슷한 사람들의 생생한 후기.",
                "후기형",
                None,
                {},
                {"decision_trigger": {"code": "similar_review", "label": "후기형"}},
            ),
            _OptionSeed(
                "C",
                "믿고 보는 뷰티 크리에이터의 추천.",
                "인플루언서형",
                None,
                {},
                {"decision_trigger": {"code": "influencer", "label": "인플루언서형"}},
            ),
            _OptionSeed(
                "D",
                "비건·친환경 같은 브랜드의 가치관.",
                "클린뷰티형",
                None,
                {},
                {"decision_trigger": {"code": "clean_beauty", "label": "클린뷰티형"}},
            ),
        ),
    ),
)


BAUMANN_PROFILE_SEEDS: tuple[_BaumannProfileSeed, ...] = (
    _BaumannProfileSeed("OSNT", "천도복숭아", "밸런스만 잡아주면 빛나는 타입", "빛나는 걸 좋아하지만, 상처엔 의외로 강해요", ("과다 피지", "모공", "컨디션성 홍조"), ("광채", "유분밸런스", "진정")),
    _BaumannProfileSeed("OSNW", "체리", "진정과 탄력을 함께 챙겨야 하는 타입", "겉은 여전히 반짝이는데, 요즘 살짝 신경 쓰이지 않나요", ("과다 피지", "트러블", "초기 잔주름"), ("진정", "탄력케어", "피지컨트롤")),
    _BaumannProfileSeed("OSPT", "방울토마토", "진정하며 자국까지 케어해야 하는 타입", "탄탄해 보여도, 스치면 은근 오래 남아요", ("트러블 후 색소침착", "모공", "홍조"), ("미백", "진정", "자국케어")),
    _BaumannProfileSeed("OSPW", "딸기", "진정과 미백이 동시에 필요한 타입", "겉과 속 모두 섬세하게 신경 써줘야 하는 타입", ("트러블", "색소침착", "잔주름"), ("저자극", "미백", "안티에이징")),
    _BaumannProfileSeed("ORNT", "망고", "기본만 해도 충분한 타입", "관리가 크게 필요 없는, 타고나길 건강한 피부", ("모공", "경미한 피지과다"), ("건강한 광채", "산뜻함")),
    _BaumannProfileSeed("ORNW", "유자", "탄력과 결만 잡아주면 되는 타입", "표면은 있는 그대로인데, 속은 흔들림 없어요", ("모공", "표면 결"), ("탄력케어", "결정돈")),
    _BaumannProfileSeed("ORPT", "오렌지", "톤 케어에 집중하면 되는 타입", "잡티는 신경 쓰이지만, 탄탄함은 그대로", ("모공", "기미", "잡티"), ("미백", "자외선차단", "톤케어")),
    _BaumannProfileSeed("ORPW", "파인애플", "미백과 탄력을 함께 챙기면 되는 타입", "무늬도 표면도 개성 있지만 속은 단단한 타입", ("색소침착", "주름", "모공"), ("미백", "안티에이징", "톤업")),
    _BaumannProfileSeed("DSNT", "백도", "진정과 장벽만 지켜주면 되는 타입", "부드러운 솜털 아래, 생각보다 섬세해요", ("당김", "홍조", "각질"), ("보습", "진정", "장벽케어")),
    _BaumannProfileSeed("DSNW", "참외", "보습과 탄력을 함께 채워야 하는 타입", "촉촉함이 부족하면 결부터 티가 나는 타입", ("당김", "잔주름", "홍조"), ("고보습", "탄력케어", "진정")),
    _BaumannProfileSeed("DSPT", "살구", "저자극으로 미백까지 챙겨야 하는 타입", "작은 자극에도 흔적이 잘 남는, 세심한 케어가 필요한 타입", ("당김", "색소침착", "홍조"), ("보습", "미백", "저자극")),
    _BaumannProfileSeed("DSPW", "미니수박", "매일 정성껏 채워줘야 하는 타입", "지금 가장 정성스러운 루틴이 필요한 타입", ("당김", "색소침착", "주름", "홍조"), ("집중보습", "미백", "안티에이징", "저자극")),
    _BaumannProfileSeed("DRNT", "사과", "기본 보습만 해도 충분한 타입", "특별한 트러블 없이 꾸준한, 안정적인 타입", ("경미한 당김",), ("촉촉함", "담백함", "기본케어")),
    _BaumannProfileSeed("DRNW", "리치", "보습과 탄력만 챙기면 되는 타입", "표면의 결은 있어도 속은 흔들림 없이 단단해요", ("당김", "잔주름"), ("보습", "탄력케어")),
    _BaumannProfileSeed("DRPT", "자몽", "보습하며 미백을 더하면 되는 타입", "잡티는 있지만 기본기가 탄탄한 타입", ("당김", "색소침착"), ("보습", "미백")),
    _BaumannProfileSeed("DRPW", "머스크멜론", "속부터 채우는 게 답인 타입", "겉은 단단해도, 안에서부터 채워주는 케어가 필요해요", ("당김", "색소침착", "주름"), ("고보습", "미백", "안티에이징")),
)


def get_skin_test_questions_response(session: Session) -> SkinTestQuestionsResponse:
    version = ensure_default_skin_test(session)
    questions = _load_questions(session, version.id)
    options_by_question_id = _load_options_by_question_id(session, [question.id for question in questions])
    return SkinTestQuestionsResponse(
        version=version.version_code,
        questions=[
            SkinTestQuestionResponse(
                id=question.id,
                text=question.question_text,
                skip_conditions=question.skip_conditions,
                options=[
                    SkinTestOptionResponse(id=option.id, text=option.label)
                    for option in options_by_question_id.get(question.id, [])
                ],
            )
            for question in questions
        ],
    )


def submit_skin_test(
    session: Session,
    request: SkinTestSubmitRequest,
    current_user: User | None = None,
) -> SkinTestResultData:
    version = ensure_default_skin_test(session)
    if request.version is not None and request.version != version.version_code:
        raise SkinServiceError(400, "INVALID_SKIN_TEST_VERSION", "피부 테스트 버전이 올바르지 않습니다.")

    questions = _load_questions(session, version.id)
    options_by_question_id = _load_options_by_question_id(session, [question.id for question in questions])
    validated_answers = _validate_answers(request.answers, questions, options_by_question_id)
    scored = _score_answers(validated_answers)
    baumann_profile = _load_baumann_type_profile(session, scored["type_code"])

    result = SkinTestResult(
        result_code=_generate_result_code(session),
        user_id=current_user.id if current_user is not None else None,
        anonymous_id=_normalize_optional_text(request.anonymous_id),
        version_id=version.id,
        baumann_type_profile_id=baumann_profile.id,
        type_code=baumann_profile.type_code,
        mapped_skin_type=baumann_profile.mapped_skin_type,
        mapped_sensitivity=baumann_profile.mapped_sensitivity,
        axis_scores=scored["axis_scores"],
        commerce_profile=scored["commerce_profile"],
        recommended_effect_ids=list(baumann_profile.keywords or baumann_profile.recommended_effect_ids or []),
        avoid_hints=baumann_profile.avoid_hints,
        raw_score_payload=scored["raw_score_payload"],
    )
    session.add(result)
    session.flush()

    for order, (question, option) in enumerate(validated_answers, start=1):
        session.add(
            SkinTestAnswer(
                result_id=result.id,
                version_id=version.id,
                question_id=question.id,
                option_id=option.id,
                answer_order=order,
                question_snapshot={
                    "question_key": question.question_key,
                    "axis": question.axis,
                    "question_text": question.question_text,
                },
                option_snapshot={
                    "option_key": option.option_key,
                    "label": option.label,
                    "internal_label": option.internal_label,
                    "axis_value": option.axis_value,
                    "score_delta": option.score_delta,
                    "commerce_mapping": option.commerce_mapping,
                },
            )
        )
    session.flush()
    if current_user is not None:
        apply_skin_test_result_to_profile(session, current_user, result.id)
    return to_skin_test_result_data(session, result)


def get_skin_test_result_data(session: Session, result_id: int) -> SkinTestResultData:
    result = _load_skin_test_result(session, result_id)
    return to_skin_test_result_data(session, result)


def apply_skin_test_result_to_profile(
    session: Session,
    user: User,
    result_id: int,
) -> SkinProfileResponse:
    result = _load_skin_test_result(session, result_id)
    if result.user_id is not None and result.user_id != user.id:
        raise SkinServiceError(403, "SKIN_TEST_RESULT_FORBIDDEN", "다른 사용자의 피부 테스트 결과입니다.")

    now = datetime.now(UTC)
    profile = load_skin_profile_for_user(session, user.id)
    if profile is None:
        profile = SkinProfile(
            user_id=user.id,
            skin_type=result.mapped_skin_type,
            sensitivity=result.mapped_sensitivity,
            skin_type_source="skin_test",
            sensitivity_source="skin_test",
            skin_type_confidence=BAUMANN_SIGNAL_WEIGHT,
            sensitivity_confidence=BAUMANN_SIGNAL_WEIGHT,
            source="skin_test",
        )
        session.add(profile)
    else:
        has_manual_skin_type = bool(profile.explicit_skin_type)
        has_manual_sensitivity = bool(profile.explicit_sensitivity)
        if not has_manual_skin_type:
            profile.skin_type = result.mapped_skin_type
            profile.skin_type_source = "skin_test"
            profile.skin_type_confidence = BAUMANN_SIGNAL_WEIGHT
        if not has_manual_sensitivity:
            profile.sensitivity = result.mapped_sensitivity
            profile.sensitivity_source = "skin_test"
            profile.sensitivity_confidence = BAUMANN_SIGNAL_WEIGHT
        profile.source = "mixed" if has_manual_skin_type or has_manual_sensitivity else "skin_test"

    profile.baumann_type_profile_id = result.baumann_type_profile_id
    profile.baumann_type_code = result.type_code
    profile.baumann_inferred_skin_type = result.mapped_skin_type
    profile.baumann_inferred_sensitivity = result.mapped_sensitivity
    profile.baumann_signal_weight = BAUMANN_SIGNAL_WEIGHT
    profile.latest_skin_test_result_id = result.id
    profile.commerce_profile = result.commerce_profile
    profile.updated_at = now
    session.flush()

    result.user_id = user.id
    result.applied_profile_id = profile.id
    result.applied_weight = BAUMANN_SIGNAL_WEIGHT
    result.applied_at = now
    session.flush()
    return SkinProfileResponse(has_profile=True, profile=to_skin_profile_data(session, profile))


def to_skin_test_result_data(session: Session, result: SkinTestResult) -> SkinTestResultData:
    baumann_profile = session.get(BaumannTypeProfile, result.baumann_type_profile_id)
    keywords = _list_or_empty(baumann_profile.keywords if baumann_profile is not None else None)
    return SkinTestResultData(
        result_id=result.id,
        skin_type=_frontend_skin_type(result.mapped_skin_type),
        sensitivity=_frontend_sensitivity(result.mapped_sensitivity),
        recommended_effects=keywords or _list_or_empty(result.recommended_effect_ids),
        avoid_hint=_list_or_empty(result.avoid_hints),
        concern_tags=_list_or_empty(baumann_profile.concern_tags if baumann_profile is not None else None),
        type_code=result.type_code,
        title=baumann_profile.title if baumann_profile is not None else f"{result.type_code} 피부 타입",
        subtitle=baumann_profile.subtitle if baumann_profile is not None else None,
        image_storage_key=baumann_profile.image_storage_key if baumann_profile is not None else None,
    )


def ensure_default_skin_test(session: Session) -> SkinTestVersion:
    _ensure_baumann_type_profiles(session)
    version = session.execute(
        select(SkinTestVersion).where(SkinTestVersion.version_code == DEFAULT_VERSION_CODE)
    ).scalar_one_or_none()
    if version is None:
        version = SkinTestVersion(
            version_code=DEFAULT_VERSION_CODE,
            title="Baumann Skin Type 기반 8문항 피부·커머스 테스트",
            description="피부 4축과 커머스 성향 4문항을 함께 수집하는 MVP 피부 테스트입니다.",
            question_count=len(QUESTION_SEEDS),
            scoring_version=DEFAULT_SCORING_VERSION,
            status="active",
            published_at=datetime.now(UTC),
        )
        session.add(version)
        session.flush()
    else:
        version.title = "Baumann Skin Type 기반 8문항 피부·커머스 테스트"
        version.description = "피부 4축과 커머스 성향 4문항을 함께 수집하는 MVP 피부 테스트입니다."
        version.question_count = len(QUESTION_SEEDS)
        version.scoring_version = DEFAULT_SCORING_VERSION
        version.status = "active"

    _sync_default_questions(session, version)
    session.flush()
    return version


def _sync_default_questions(session: Session, version: SkinTestVersion) -> None:
    existing_questions = {
        question.question_key: question
        for question in session.execute(
            select(SkinTestQuestion).where(SkinTestQuestion.version_id == version.id)
        ).scalars()
    }
    for question_seed in QUESTION_SEEDS:
        question = existing_questions.get(question_seed.question_key)
        if question is None:
            question = SkinTestQuestion(
                version_id=version.id,
                question_key=question_seed.question_key,
                sequence=question_seed.sequence,
                axis=question_seed.axis,
                question_text=question_seed.question_text,
            )
            session.add(question)
            session.flush()
        question.sequence = question_seed.sequence
        question.axis = question_seed.axis
        question.question_text = question_seed.question_text
        question.helper_text = question_seed.helper_text
        question.is_required = True
        question.is_active = True
        _sync_default_options(session, question, question_seed.options)


def _sync_default_options(
    session: Session,
    question: SkinTestQuestion,
    option_seeds: tuple[_OptionSeed, ...],
) -> None:
    existing_options = {
        option.option_key: option
        for option in session.execute(
            select(SkinTestOption).where(SkinTestOption.question_id == question.id)
        ).scalars()
    }
    for display_order, option_seed in enumerate(option_seeds, start=1):
        option = existing_options.get(option_seed.option_key)
        if option is None:
            option = SkinTestOption(question_id=question.id, option_key=option_seed.option_key)
            session.add(option)
        option.display_order = display_order
        option.label = option_seed.label
        option.internal_label = option_seed.internal_label
        option.axis_value = option_seed.axis_value
        option.score_delta = option_seed.score_delta
        option.commerce_mapping = option_seed.commerce_mapping


def _ensure_baumann_type_profiles(session: Session) -> None:
    existing_profiles = {
        profile.type_code: profile
        for profile in session.execute(select(BaumannTypeProfile)).scalars()
    }
    for display_order, seed in enumerate(BAUMANN_PROFILE_SEEDS, start=1):
        profile = existing_profiles.get(seed.type_code)
        if profile is None:
            profile = BaumannTypeProfile(type_code=seed.type_code)
            session.add(profile)
        profile.object_name = seed.object_name
        profile.title = seed.title
        profile.subtitle = seed.subtitle
        profile.description = f"{seed.object_name} 오브제로 표현한 {seed.type_code} 피부 타입입니다."
        profile.image_storage_key = f"skin-types/{seed.type_code}/{seed.type_code}.png"
        profile.mapped_skin_type = "지성" if seed.type_code[0] == "O" else "건성"
        profile.mapped_sensitivity = "민감" if seed.type_code[1] == "S" else "보통"
        profile.concern_tags = list(seed.concern_tags)
        profile.recommended_effect_ids = list(seed.keywords)
        profile.avoid_hints = _avoid_hints(seed.type_code)
        profile.keywords = list(seed.keywords)
        profile.display_order = display_order
        profile.is_active = True
    session.flush()


def _avoid_hints(type_code: str) -> list[str]:
    hints: list[str] = []
    if type_code[1] == "S":
        hints.append("자극 가능성이 있는 고기능성 성분은 낮은 빈도로 천천히 테스트하세요.")
    if type_code[0] == "D":
        hints.append("건조감을 키울 수 있는 과한 세정 루틴은 피하는 편이 좋습니다.")
    if type_code[2] == "P":
        hints.append("흔적 케어를 위해 낮 시간 자외선 차단을 함께 챙기는 편이 좋습니다.")
    if type_code[3] == "W":
        hints.append("주름·탄력 케어는 보습 루틴과 함께 보는 편이 좋습니다.")
    return hints


def _load_questions(session: Session, version_id: int) -> list[SkinTestQuestion]:
    return list(
        session.execute(
            select(SkinTestQuestion)
            .where(
                SkinTestQuestion.version_id == version_id,
                SkinTestQuestion.is_active.is_(True),
            )
            .order_by(SkinTestQuestion.sequence)
        ).scalars()
    )


def _load_options_by_question_id(
    session: Session,
    question_ids: list[int],
) -> dict[int, list[SkinTestOption]]:
    if not question_ids:
        return {}
    options = session.execute(
        select(SkinTestOption)
        .where(SkinTestOption.question_id.in_(question_ids))
        .order_by(SkinTestOption.question_id, SkinTestOption.display_order)
    ).scalars()
    grouped: dict[int, list[SkinTestOption]] = {}
    for option in options:
        grouped.setdefault(option.question_id, []).append(option)
    return grouped


def _validate_answers(
    answers: list[SkinTestAnswerInput],
    questions: list[SkinTestQuestion],
    options_by_question_id: dict[int, list[SkinTestOption]],
) -> list[tuple[SkinTestQuestion, SkinTestOption]]:
    questions_by_id = {question.id: question for question in questions}
    options_by_id = {
        option.id: option
        for options in options_by_question_id.values()
        for option in options
    }
    required_question_ids = {question.id for question in questions if question.is_required}
    seen_question_ids: set[int] = set()
    validated: list[tuple[SkinTestQuestion, SkinTestOption]] = []

    for answer in answers:
        question = questions_by_id.get(answer.question_id)
        if question is None:
            raise SkinServiceError(400, "UNKNOWN_SKIN_TEST_QUESTION", "피부 테스트 질문이 올바르지 않습니다.")
        if question.id in seen_question_ids:
            raise SkinServiceError(400, "DUPLICATE_SKIN_TEST_ANSWER", "중복된 피부 테스트 답변이 있습니다.")
        option = options_by_id.get(answer.option_id)
        if option is None or option.question_id != question.id:
            raise SkinServiceError(400, "OPTION_NOT_IN_QUESTION", "질문과 선택지 조합이 올바르지 않습니다.")
        seen_question_ids.add(question.id)
        validated.append((question, option))

    missing = required_question_ids - seen_question_ids
    if missing:
        raise SkinServiceError(400, "MISSING_SKIN_TEST_ANSWER", "필수 피부 테스트 답변이 누락되었습니다.")
    return validated


def _score_answers(validated_answers: list[tuple[SkinTestQuestion, SkinTestOption]]) -> dict:
    raw_axis_scores = {axis: {left: 0, right: 0} for axis, (left, right) in AXIS_PAIRS.items()}
    commerce_profile: dict = {}
    raw_options = []

    for question, option in validated_answers:
        for axis_value, delta in (option.score_delta or {}).items():
            for axis_scores in raw_axis_scores.values():
                if axis_value in axis_scores:
                    axis_scores[axis_value] += int(delta)
        if option.commerce_mapping:
            commerce_profile.update(option.commerce_mapping)
        raw_options.append(
            {
                "question_key": question.question_key,
                "option_key": option.option_key,
                "axis": question.axis,
                "internal_label": option.internal_label,
                "axis_value": option.axis_value,
                "score_delta": option.score_delta,
                "commerce_mapping": option.commerce_mapping,
            }
        )

    axis_scores: dict = {}
    winners: list[str] = []
    for axis, (left, right) in AXIS_PAIRS.items():
        left_score = raw_axis_scores[axis][left]
        right_score = raw_axis_scores[axis][right]
        winner = left if left_score >= right_score else right
        diff = abs(left_score - right_score)
        winners.append(winner)
        axis_scores[axis] = {
            left: left_score,
            right: right_score,
            "winner": winner,
            "strength": "strong" if diff >= 2 else "weak",
        }

    type_code = "".join(winners)
    return {
        "type_code": type_code,
        "axis_scores": axis_scores,
        "commerce_profile": commerce_profile,
        "raw_score_payload": {
            "scoring_version": DEFAULT_SCORING_VERSION,
            "selected_options": raw_options,
        },
    }


def _load_baumann_type_profile(session: Session, type_code: str) -> BaumannTypeProfile:
    profile = session.execute(
        select(BaumannTypeProfile).where(BaumannTypeProfile.type_code == type_code)
    ).scalar_one_or_none()
    if profile is None:
        raise SkinServiceError(500, "BAUMANN_TYPE_PROFILE_MISSING", "Baumann 타입 기준표가 없습니다.")
    return profile


def _load_skin_test_result(session: Session, result_id: int) -> SkinTestResult:
    result = session.get(SkinTestResult, result_id)
    if result is None:
        raise SkinServiceError(404, "SKIN_TEST_RESULT_NOT_FOUND", "피부 테스트 결과를 찾을 수 없습니다.")
    return result


def _generate_result_code(session: Session) -> str:
    for _ in range(10):
        result_code = f"skinres_{secrets.token_urlsafe(18)}"
        exists = session.execute(
            select(SkinTestResult.id).where(SkinTestResult.result_code == result_code)
        ).scalar_one_or_none()
        if exists is None:
            return result_code
    raise SkinServiceError(500, "SKIN_RESULT_CODE_GENERATION_FAILED", "피부 테스트 결과 ID 생성에 실패했습니다.")


def _frontend_skin_type(mapped_skin_type: str) -> str:
    return {
        "건성": "dry",
        "지성": "oily",
        "복합성": "combination",
        "중성": "normal",
        "수부지": "dehydrated_oily",
    }.get(mapped_skin_type, mapped_skin_type)


def _frontend_sensitivity(mapped_sensitivity: str) -> str:
    return {
        "낮음": "low",
        "보통": "medium",
        "높음": "high",
        "민감": "high",
    }.get(mapped_sensitivity, mapped_sensitivity)


def _list_or_empty(value: list | tuple | dict | None) -> list[str]:
    if isinstance(value, dict):
        return [str(item) for item in value.values()]
    if value is None:
        return []
    return [str(item) for item in value]


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
