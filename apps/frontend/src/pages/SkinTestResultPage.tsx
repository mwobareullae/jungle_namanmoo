import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";
import { api } from "../lib/api";
import {
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
  const [searchParams] = useSearchParams();
  const locationState = location.state as SkinTestResultLocationState | null;
  const [result, setResult] = useState<SkinTestResult | null>(() => locationState?.result ?? getLatestSkinTestResult());
  const [imageFailed, setImageFailed] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isApplying, setIsApplying] = useState(false);

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

  const handleApplyAndRecommend = async () => {
    if (!result) {
      navigate("/skin-test");
      return;
    }

    setIsApplying(true);
    setErrorMessage("");

    try {
      await api.applySkinTestResult(result.result_id);
      navigate("/", { replace: false });
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setIsApplying(false);
    }
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
      <AuthHeader />
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
                  onClick={handleApplyAndRecommend}
                  type="button"
                >
                  {isApplying ? "프로필 반영 중" : "내 피부 맞춤 추천 보기"}
                </button>
                <button className="skin-test-secondary-button" onClick={handleShare} type="button">
                  결과 공유하기
                </button>
                <button className="skin-test-secondary-button" onClick={() => navigate("/skin-test")} type="button">
                  테스트 다시 하기
                </button>
              </div>

              <Link className="skin-test-result__home-link" to="/">
                홈으로 이동
              </Link>

              {shareMessage && <p className="skin-test-result__share">{shareMessage}</p>}
              {errorMessage && <p className="skin-test-result__error">{errorMessage}</p>}
            </>
          )}
        </section>
      </main>
    </div>
  );
}

export default SkinTestResultPage;
