import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import SkinTestProgress from "../components/SkinTestProgress";
import SkinTestQuestionCard from "../components/SkinTestQuestionCard";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import { getLatestSkinTestResult, saveLatestSkinTestResult } from "../lib/skinTest";
import { useSkinProfileQuery } from "../hooks/useSkinProfileQuery";
import type { ApiError } from "../types/recommendation";
import type { SkinTestOption, SkinTestQuestionsResponse } from "../types/skinTest";

type AnswerMap = Record<string, SkinTestOption["id"]>;

type SkinTestLocationState = {
  forceRetest?: boolean;
};

const getErrorMessage = (error: unknown) => {
  const apiError = error as Partial<ApiError>;

  if (apiError.message) {
    return apiError.message;
  }

  return "피부 타입 테스트를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
};

function SkinTestPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthLoading, user } = useAuth();
  const skinProfileQuery = useSkinProfileQuery(user?.id ?? null, !isAuthLoading && Boolean(user));
  const locationState = location.state as SkinTestLocationState | null;
  const shouldForceRetest = locationState?.forceRetest === true;
  const [questionSet, setQuestionSet] = useState<SkinTestQuestionsResponse | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [errorMessage, setErrorMessage] = useState("");
  const [hasStarted, setHasStarted] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isExistingResultResolved, setIsExistingResultResolved] = useState(shouldForceRetest);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const advanceTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (advanceTimerRef.current !== null) {
        window.clearTimeout(advanceTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (shouldForceRetest) {
      return;
    }

    const latestResult = getLatestSkinTestResult();
    if (latestResult) {
      navigate(`/skin-test/result?result_id=${latestResult.result_id}`, {
        replace: true,
        state: { result: latestResult },
      });
      return;
    }

    if (isAuthLoading) {
      return;
    }

    if (!user) {
      queueMicrotask(() => setIsExistingResultResolved(true));
      return;
    }

    if (skinProfileQuery.isPending) {
      return;
    }

    if (skinProfileQuery.data?.latestSkinTestResultId) {
      navigate(`/skin-test/result?result_id=${skinProfileQuery.data.latestSkinTestResultId}`, { replace: true });
      return;
    }

    setIsExistingResultResolved(true);
  }, [isAuthLoading, navigate, shouldForceRetest, skinProfileQuery.data, skinProfileQuery.isPending, user]);

  useEffect(() => {
    if (!isExistingResultResolved) {
      return;
    }

    let isActive = true;

    const loadQuestions = async () => {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await api.getSkinTestQuestions();

        if (!isActive) {
          return;
        }

        setQuestionSet(response);
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

    void loadQuestions();

    return () => {
      isActive = false;
    };
  }, [isExistingResultResolved]);

  const questions = useMemo(() => questionSet?.questions ?? [], [questionSet?.questions]);
  const currentQuestion = questions[currentIndex];
  const selectedOptionId = currentQuestion ? answers[String(currentQuestion.id)] ?? null : null;
  const isLastQuestion = currentIndex === questions.length - 1;
  const answeredCount = useMemo(
    () => questions.filter((question) => answers[String(question.id)] !== undefined).length,
    [answers, questions],
  );
  const isQuestionStep = Boolean(currentQuestion && hasStarted && !isSubmitting && !isLoading);

  const submitAnswers = async (finalAnswers: AnswerMap) => {
    if (!questionSet) {
      return;
    }

    const unansweredQuestion = questions.find((question) => finalAnswers[String(question.id)] === undefined);

    if (unansweredQuestion) {
      setCurrentIndex(questions.indexOf(unansweredQuestion));
      setErrorMessage("모든 문항에 답변해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");

    try {
      const [result] = await Promise.all([
        api.submitSkinTest({
          version: questionSet.version,
          answers: questions.map((question) => ({
            question_id: question.id,
            option_id: finalAnswers[String(question.id)],
          })),
        }),
        new Promise((resolve) => window.setTimeout(resolve, 700)),
      ]);

      saveLatestSkinTestResult(result);
      navigate(`/skin-test/result?result_id=${result.result_id}`, {
        state: {
          result,
        },
      });
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  const advanceToNext = (nextAnswers: AnswerMap) => {
    if (!isLastQuestion) {
      setCurrentIndex((index) => index + 1);
      return;
    }

    void submitAnswers(nextAnswers);
  };

  // commit === false: 화살표 키로 훑어보는 중(Radix가 포커스 이동 시 자동으로 클릭 처리함).
  // 선택 표시/카운터만 갱신하고 자동 진행은 하지 않는다 — 그래야 3번 문항까지 화살표로 이동 가능.
  const handleSelectOption = (optionId: SkinTestOption["id"], commit: boolean) => {
    if (!currentQuestion || isSubmitting) {
      return;
    }

    const nextAnswers = {
      ...answers,
      [String(currentQuestion.id)]: optionId,
    };

    setAnswers(nextAnswers);
    setErrorMessage("");

    if (advanceTimerRef.current !== null) {
      window.clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }

    if (!commit) {
      return;
    }

    advanceTimerRef.current = window.setTimeout(() => {
      advanceTimerRef.current = null;
      advanceToNext(nextAnswers);
    }, 180);
  };

  // 화살표로 훑어보다 Enter로 확정할 때 호출. Radix의 자동 클릭이 타이밍상 안 걸릴 때가 많아서,
  // answers 상태가 아니라 "지금 포커스가 가 있는 항목"을 카드 쪽에서 직접 넘겨받아 그걸로 확정한다.
  const handleConfirmSelection = (optionId: SkinTestOption["id"] | null) => {
    if (!currentQuestion || isSubmitting || optionId === null) {
      return;
    }

    if (advanceTimerRef.current !== null) {
      window.clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }

    const nextAnswers = {
      ...answers,
      [String(currentQuestion.id)]: optionId,
    };

    setAnswers(nextAnswers);
    setErrorMessage("");
    advanceToNext(nextAnswers);
  };

  const handlePrevious = () => {
    setErrorMessage("");

    if (currentIndex === 0) {
      setHasStarted(false);
      return;
    }

    setCurrentIndex((index) => index - 1);
  };

  return (
    <div className="skin-test-shell">
      <HomeHeader />
      <main className="skin-test-main">
        <div className={`skin-test-layout${isQuestionStep ? " skin-test-layout--question" : ""}`}>
          <section className="skin-test-panel" aria-live="polite">
            {isSubmitting ? (
              <div className="skin-test-state skin-test-state--analysis">
                <span className="skin-test-loader" aria-hidden="true" />
                <p>
                  당신의 피부 타입을
                  <br />
                  분석 중...
                </p>
                <small>약 8문항의 답변을 조합하고 있어요</small>
              </div>
            ) : !isExistingResultResolved ? (
              <div className="skin-test-state">
                <span className="skin-test-loader" aria-hidden="true" />
                <p>저장된 피부 타입 결과를 확인하고 있어요.</p>
              </div>
            ) : isLoading ? (
              <div className="skin-test-state">
                <span className="skin-test-loader" aria-hidden="true" />
                <p>문항을 불러오고 있어요.</p>
              </div>
            ) : !currentQuestion ? (
              <div className="skin-test-state">
                <p>사용 가능한 피부 타입 테스트 문항이 없습니다.</p>
                <button className="skin-test-primary-button" onClick={() => navigate("/")} type="button">
                  홈으로 이동
                </button>
              </div>
            ) : !hasStarted ? (
              <div className="skin-test-intro">
                <p className="skin-test-intro__eyebrow">맞춤 추천 테스트</p>
                <h1>내 피부 상태 셀프 진단하기</h1>
                <p className="skin-test-intro__copy">
                  몇 가지 질문에 답하면 피부 타입과 고민을 바탕으로 맞춤 추천을 준비해드려요.
                </p>
                <div className="skin-test-intro-card" aria-hidden="true">
                  <strong>뭐바를래 피부 체크인</strong>
                  <em>내 피부에 맞는 추천 여정의 시작</em>
                </div>
                <button className="skin-test-intro-button" onClick={() => setHasStarted(true)} type="button">
                  셀프 체크인 시작하기
                </button>
              </div>
            ) : (
              <div className="skin-test-question-frame" key={currentQuestion.id}>
                <SkinTestProgress current={currentIndex + 1} onBack={handlePrevious} total={questions.length} />
                <SkinTestQuestionCard
                  question={currentQuestion}
                  selectedOptionId={selectedOptionId}
                  onSelect={handleSelectOption}
                  onConfirm={handleConfirmSelection}
                />
                <div className="skin-test-question-actions">
                  <button
                    className="skin-test-primary-button"
                    disabled={selectedOptionId === null}
                    onClick={() => handleConfirmSelection(selectedOptionId)}
                    type="button"
                  >
                    {isLastQuestion ? "결과 확인하기" : "다음"}
                    <span aria-hidden="true">→</span>
                  </button>
                </div>
                <div className="skin-test-footnote">
                  <span>
                    {answeredCount}/{questions.length} 답변 완료
                  </span>
                  {errorMessage && <strong>{errorMessage}</strong>}
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

export default SkinTestPage;
