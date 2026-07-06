import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import SkinTestProgress from "../components/SkinTestProgress";
import SkinTestQuestionCard from "../components/SkinTestQuestionCard";
import { api } from "../lib/api";
import { saveLatestSkinTestResult } from "../lib/skinTest";
import type { ApiError } from "../types/recommendation";
import type { SkinTestOption, SkinTestQuestionsResponse } from "../types/skinTest";

type AnswerMap = Record<string, SkinTestOption["id"]>;

const getErrorMessage = (error: unknown) => {
  const apiError = error as Partial<ApiError>;

  if (apiError.message) {
    return apiError.message;
  }

  return "피부 타입 테스트를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
};

function SkinTestPage() {
  const navigate = useNavigate();
  const [questionSet, setQuestionSet] = useState<SkinTestQuestionsResponse | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
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
  }, []);

  const questions = useMemo(() => questionSet?.questions ?? [], [questionSet?.questions]);
  const currentQuestion = questions[currentIndex];
  const selectedOptionId = currentQuestion ? answers[String(currentQuestion.id)] ?? null : null;
  const isLastQuestion = currentIndex === questions.length - 1;
  const answeredCount = useMemo(
    () => questions.filter((question) => answers[String(question.id)] !== undefined).length,
    [answers, questions],
  );

  const handleSelectOption = (optionId: SkinTestOption["id"]) => {
    if (!currentQuestion) {
      return;
    }

    setAnswers((currentAnswers) => ({
      ...currentAnswers,
      [String(currentQuestion.id)]: optionId,
    }));
    setErrorMessage("");
  };

  const handlePrevious = () => {
    setErrorMessage("");

    if (currentIndex === 0) {
      navigate("/");
      return;
    }

    setCurrentIndex((index) => index - 1);
  };

  const handleNext = async () => {
    if (!currentQuestion || !questionSet) {
      return;
    }

    if (selectedOptionId === null) {
      setErrorMessage("답변을 하나 선택해 주세요.");
      return;
    }

    if (!isLastQuestion) {
      setCurrentIndex((index) => index + 1);
      setErrorMessage("");
      return;
    }

    const unansweredQuestion = questions.find((question) => answers[String(question.id)] === undefined);

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
            option_id: answers[String(question.id)],
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

  return (
    <div className="skin-test-shell">
      <HomeHeader />
      <main className="skin-test-main">
        <div className="skin-test-layout">
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
            ) : (
              <>
                <SkinTestProgress current={currentIndex + 1} onBack={handlePrevious} total={questions.length} />
                <SkinTestQuestionCard
                  question={currentQuestion}
                  selectedOptionId={selectedOptionId}
                  onSelect={handleSelectOption}
                />
                <div className="skin-test-actions">
                  <button
                    className="skin-test-primary-button"
                    disabled={isSubmitting || selectedOptionId === null}
                    onClick={handleNext}
                    type="button"
                  >
                    {isLastQuestion ? "결과 보기" : "확인"}
                  </button>
                </div>
                <div className="skin-test-footnote">
                  <span>{answeredCount}개 답변 완료</span>
                  {errorMessage && <strong>{errorMessage}</strong>}
                </div>
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

export default SkinTestPage;
