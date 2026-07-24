import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import { Dialog, DialogClose, DialogRawContent } from "../components/ui/dialog";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import {
  clearLatestSkinTestResult,
  getLatestSkinTestResult,
  getSensitivityLabel,
  getSkinTestImageUrl,
  getSkinTypeLabel,
  saveLatestSkinTestResult,
} from "../lib/skinTest";
import type { ApiError } from "../types/recommendation";
import type { SkinTestResult } from "../types/skinTest";

type SkinTestResultLocationState = {
  result?: SkinTestResult;
};

const PENDING_RECOMMENDATION_RESULT_KEY = "mwobareullae.skinTest.pendingRecommendationResultId";

const getErrorMessage = (error: unknown) => {
  const apiError = error as Partial<ApiError>;

  if (apiError.message) {
    return apiError.message;
  }

  return "피부 타입 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
};

function SkinTestResultPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const locationState = location.state as SkinTestResultLocationState | null;
  const [result, setResult] = useState<SkinTestResult | null>(() => locationState?.result ?? getLatestSkinTestResult());
  const [imageFailed, setImageFailed] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [isRecommendModalOpen, setIsRecommendModalOpen] = useState(false);

  const resultId = useMemo(() => {
    const queryResultId = Number(searchParams.get("result_id"));

    if (Number.isFinite(queryResultId) && queryResultId > 0) {
      return queryResultId;
    }

    return result?.result_id ?? null;
  }, [result?.result_id, searchParams]);

  useEffect(() => {
    if (locationState?.result) {
      saveLatestSkinTestResult(locationState.result);
      return;
    }

    if (!resultId || result?.result_id === resultId) {
      return;
    }

    let isActive = true;

    const loadResult = async () => {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await api.getSkinTestResult(resultId);

        if (!isActive) {
          return;
        }

        setResult(response.result);
        saveLatestSkinTestResult(response.result);
      } catch (error) {
        if (isActive) {
          setErrorMessage(getErrorMessage(error));
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    void loadResult();

    return () => {
      isActive = false;
    };
  }, [locationState?.result, result?.result_id, resultId]);

  const imageUrl = getSkinTestImageUrl(result?.image_storage_key);
  const typeCode = result?.type_code ?? "TYPE";
  const title = result?.title ?? "피부 타입 분석 결과";
  const subtitle = result?.subtitle ?? "답변을 바탕으로 피부 프로필을 정리했어요.";
  const concernTags = result?.concern_tags ?? result?.avoid_hint ?? [];
  const recommendedEffects = result?.recommended_effects ?? [];
  const [shareMessage, setShareMessage] = useState("");

  const navigateToRecommendations = useCallback(
    (nextResult: SkinTestResult) => {
      navigate(`/skin-test/recommendations?result_id=${nextResult.result_id}`, {
        replace: false,
        state: { result: nextResult },
      });
    },
    [navigate]
  );

  const applyResultAndRecommend = useCallback(
    async (nextResult: SkinTestResult) => {
      setIsApplying(true);
      setErrorMessage("");
      let didApplyToProfile = false;

      try {
        await api.applySkinTestResult(nextResult.result_id);
        didApplyToProfile = true;
      } catch {
        // Recommendation page can still use result_id even if profile persistence is not ready.
      } finally {
        if (didApplyToProfile) {
          clearLatestSkinTestResult();
        }
        setIsApplying(false);
        setIsRecommendModalOpen(false);
        navigateToRecommendations(nextResult);
      }
    },
    [navigateToRecommendations]
  );

  useEffect(() => {
    if (!user || !result) {
      return;
    }

    const pendingResultId = sessionStorage.getItem(PENDING_RECOMMENDATION_RESULT_KEY);
    if (pendingResultId !== String(result.result_id)) {
      return;
    }

    sessionStorage.removeItem(PENDING_RECOMMENDATION_RESULT_KEY);
    const timerId = window.setTimeout(() => {
      void applyResultAndRecommend(result);
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [applyResultAndRecommend, result, user]);

  const handleRecommendClick = () => {
    if (!result) {
      navigate("/skin-test");
      return;
    }

    setIsRecommendModalOpen(true);
  };

  const handleConfirmRecommend = () => {
    if (!result) {
      return;
    }

    if (user) {
      void applyResultAndRecommend(result);
      return;
    }

    sessionStorage.setItem(PENDING_RECOMMENDATION_RESULT_KEY, String(result.result_id));
    navigate("/login", {
      state: { from: `${location.pathname}${location.search}${location.hash}` }
    });
  };

  const handleSkipSaveAndRecommend = () => {
    if (!result) {
      return;
    }

    setIsRecommendModalOpen(false);
    navigateToRecommendations(result);
  };

  const handleShare = async () => {
    const resultUrl = window.location.href;

    try {
      await navigator.clipboard.writeText(resultUrl);
      setShareMessage("결과 링크를 복사했어요.");
    } catch {
      setShareMessage("현재 브라우저에서는 링크 복사가 지원되지 않아요.");
    }
  };

  return (
    <div className="skin-test-shell">
      <HomeHeader />
      <main className="skin-test-main skin-test-result-main">
        <section className="skin-test-result">
          {isLoading ? (
            <div className="skin-test-state">
              <span className="skin-test-loader" aria-hidden="true" />
              <p>결과를 불러오고 있어요.</p>
            </div>
          ) : !result ? (
            <div className="skin-test-state">
              <p>{errorMessage || "피부 타입 테스트 결과가 없습니다."}</p>
              <button className="skin-test-primary-button" onClick={() => navigate("/skin-test")} type="button">
                테스트 시작하기
              </button>
            </div>
          ) : (
            <>
              <div className="skin-test-result__visual">
                {imageUrl && !imageFailed ? (
                  <img
                    alt={`${typeCode} 피부 타입 결과 이미지`}
                    loading="lazy"
                    onError={() => setImageFailed(true)}
                    src={imageUrl}
                  />
                ) : (
                  <div className="skin-test-result__image-fallback" aria-label="피부 타입 결과 이미지 준비 중">
                    {typeCode}
                  </div>
                )}
              </div>

              <p className="skin-test-result__code">{typeCode}</p>
              <h1>{title}</h1>
              <p className="skin-test-result__subtitle">{subtitle}</p>

              <p className="skin-test-result__profile">
                {getSkinTypeLabel(result.skin_type)} · 민감도 {getSensitivityLabel(result.sensitivity)}
              </p>

              <div className="skin-test-result__sections">
                {concernTags.length > 0 && (
                  <section>
                    <h2>내 피부 고민</h2>
                    <div className="skin-test-tags">
                      {concernTags.map((tag) => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                  </section>
                )}

                <section>
                  <h2>추천 케어 키워드</h2>
                  <div className="skin-test-tags skin-test-tags--accent">
                    {recommendedEffects.map((effect) => (
                      <span key={effect}>{effect}</span>
                    ))}
                  </div>
                </section>
              </div>

              <div className="skin-test-result__actions">
                <button
                  className="skin-test-primary-button"
                  disabled={isApplying}
                  onClick={handleRecommendClick}
                  type="button"
                >
                  {isApplying ? "추천 화면 준비 중" : "내 피부에 맞는 상품 보기"}
                </button>
                <button className="skin-test-secondary-button" onClick={handleShare} type="button">
                  결과 공유하기
                </button>
                <button
                  className="skin-test-secondary-button"
                  onClick={() => navigate("/skin-test", { state: { forceRetest: true } })}
                  type="button"
                >
                  테스트 다시 하기
                </button>
              </div>

              <Link className="skin-test-result__home-link" to="/">
                홈으로 이동
              </Link>

              {shareMessage && <p className="skin-test-result__share">{shareMessage}</p>}
              {errorMessage && <p className="skin-test-result__error">{errorMessage}</p>}
              <Dialog
                onOpenChange={(open) => {
                  if (!open && isApplying) {
                    return;
                  }
                  setIsRecommendModalOpen(open);
                }}
                open={isRecommendModalOpen}
              >
                <DialogRawContent
                  aria-labelledby="skin-test-recommend-modal-title"
                  className="skin-test-recommend-modal-content-wrap"
                  overlayClassName="skin-test-recommend-modal-backdrop"
                  onClick={(event) => {
                    if (event.target === event.currentTarget && !isApplying) {
                      setIsRecommendModalOpen(false);
                    }
                  }}
                >
                  <section className="skin-test-recommend-modal">
                    <h2 id="skin-test-recommend-modal-title">
                      {user
                        ? "이 테스트 결과를 피부 프로필에 반영할까요?"
                        : "로그인하면 이 결과를 저장할 수 있어요"}
                    </h2>
                    <p>
                      {user
                        ? "반영하면 맞춤 추천 기준이 이 결과로 업데이트됩니다."
                        : "로그인하면 테스트 결과를 마이페이지에 저장하고 다음 추천에도 활용할 수 있어요."}
                    </p>
                    <div className="skin-test-recommend-modal__actions">
                      <button
                        className="skin-test-primary-button"
                        disabled={isApplying}
                        onClick={handleConfirmRecommend}
                        type="button"
                      >
                        {user ? "반영하고 추천 보기" : "로그인하고 추천 보기"}
                      </button>
                      <button
                        className="skin-test-secondary-button"
                        disabled={isApplying}
                        onClick={handleSkipSaveAndRecommend}
                        type="button"
                      >
                        {user ? "이번만 추천 보기" : "바로 추천 보기"}
                      </button>
                    </div>
                    <DialogClose asChild disabled={isApplying}>
                      <button
                        aria-label="추천 보기 확인 닫기"
                        className="skin-test-recommend-modal__close"
                        type="button"
                      >
                        닫기
                      </button>
                    </DialogClose>
                  </section>
                </DialogRawContent>
              </Dialog>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

export default SkinTestResultPage;
