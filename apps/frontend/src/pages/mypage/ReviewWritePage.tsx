import { useEffect, useMemo, useState, type FormEvent } from "react";
import ActivityToast from "../../components/ui/ActivityToast";
import ConfirmModal from "../../components/ui/ConfirmModal";
import Skeleton from "../../components/ui/Skeleton";
import { useActivityToast } from "../../hooks/useActivityToast";
import { getProductImageUrl } from "../../lib/imageUrls";
import { clearAgentReviewDraft, readAgentReviewDraft } from "../../lib/agentDrafts";
import {
  createProductReview,
  deleteProductReview,
  getMyProductReviews,
  getReviewableOrderItems,
  updateProductReview
} from "../../lib/reviewApi";
import type { MyProductReviewItem, ReviewableOrderItem } from "../../types/review";
import { MyPageLayout, PageTitle } from "./MyPageShell";

const readOrderCode = () => new URLSearchParams(window.location.search).get("order_code") ?? "";

function ReviewWritePage() {
  const [orderCode] = useState(readOrderCode);
  const [items, setItems] = useState<ReviewableOrderItem[]>([]);
  const [myReviews, setMyReviews] = useState<MyProductReviewItem[]>([]);
  const [activeTab, setActiveTab] = useState<"write" | "mine">("write");
  const [selectedItem, setSelectedItem] = useState<ReviewableOrderItem | null>(null);
  const [rating, setRating] = useState(5);
  const [reviewText, setReviewText] = useState("");
  const [isRepurchase, setIsRepurchase] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [editingReview, setEditingReview] = useState<MyProductReviewItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MyProductReviewItem | null>(null);
  const { message: toastMessage, showToast } = useActivityToast();

  useEffect(() => {
    let isMounted = true;
    const agentDraft = readAgentReviewDraft();
    Promise.all([getReviewableOrderItems(), getMyProductReviews()])
      .then(([reviewableResponse, reviewsResponse]) => {
        if (isMounted) {
          const reviewableItems = reviewableResponse.items.filter((item) => item.can_write);
          setItems(reviewableItems);
          setMyReviews(reviewsResponse.items);
          const draftItem = agentDraft
            ? reviewableItems.find((item) => item.order_item_id === agentDraft.order_item_id)
            : null;
          if (agentDraft && draftItem) {
            setSelectedItem(draftItem);
            setRating(agentDraft.rating);
            setReviewText(agentDraft.review_text);
            setIsRepurchase(agentDraft.is_repurchase_review);
            clearAgentReviewDraft();
          }
        }
      })
      .catch(() => {
        if (isMounted) {
          setItems([]);
          setErrorMessage("리뷰 목록을 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const visibleItems = useMemo(
    () => orderCode ? items.filter((item) => item.order_code === orderCode) : items,
    [items, orderCode]
  );

  const selectItem = (item: ReviewableOrderItem) => {
    setSelectedItem(item);
    setRating(5);
    setReviewText("");
    setIsRepurchase(false);
    setErrorMessage("");
  };

  const selectReviewToEdit = (item: MyProductReviewItem) => {
    setEditingReview(item);
    setSelectedItem(null);
    setRating(item.review.rating ?? 5);
    setReviewText(item.review.review_text ?? "");
    setIsRepurchase(Boolean(item.review.is_repurchase_review));
    setErrorMessage("");
  };

  const submitReview = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedItem || isSubmitting) return;
    const normalizedText = reviewText.trim();
    if (!normalizedText) {
      setErrorMessage("리뷰 내용을 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await createProductReview(selectedItem.product_id, {
        order_item_id: selectedItem.order_item_id,
        rating,
        review_text: normalizedText,
        is_repurchase_review: isRepurchase
      });
      setItems((current) => current.filter((item) => item.order_item_id !== selectedItem.order_item_id));
      setSelectedItem(null);
      setReviewText("");
      showToast("리뷰가 등록되었습니다.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "리뷰를 등록하지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const submitReviewUpdate = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingReview || isSubmitting) return;
    const normalizedText = reviewText.trim();
    if (!normalizedText) {
      setErrorMessage("리뷰 내용을 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await updateProductReview(editingReview.review.review_id, {
        rating,
        review_text: normalizedText,
        is_repurchase_review: isRepurchase
      });
      setMyReviews((current) => current.map((item) => item.review.review_id === editingReview.review.review_id
        ? {
            ...item,
            review: {
              ...item.review,
              rating,
              review_text: normalizedText,
              is_repurchase_review: isRepurchase
            }
          }
        : item));
      setEditingReview(null);
      showToast("리뷰가 수정되었습니다.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "리뷰를 수정하지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const confirmReviewDelete = async () => {
    if (!deleteTarget || isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage("");
    try {
      await deleteProductReview(deleteTarget.review.review_id);
      setMyReviews((current) => current.filter((item) => item.review.review_id !== deleteTarget.review.review_id));
      setDeleteTarget(null);
      setEditingReview(null);
      showToast("리뷰가 삭제되었습니다.");
    } catch (error) {
      setDeleteTarget(null);
      setErrorMessage(error instanceof Error ? error.message : "리뷰를 삭제하지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <MyPageLayout>
      <PageTitle title="리뷰 관리" />
      <div className="review-write-page">
        <div className="review-write-page__tabs" role="tablist" aria-label="리뷰 메뉴">
          <button
            aria-selected={activeTab === "write"}
            className={activeTab === "write" ? "is-active" : ""}
            onClick={() => {
              setActiveTab("write");
              setEditingReview(null);
              setErrorMessage("");
            }}
            role="tab"
            type="button"
          >작성 가능한 리뷰 <span>{visibleItems.length}</span></button>
          <button
            aria-selected={activeTab === "mine"}
            className={activeTab === "mine" ? "is-active" : ""}
            onClick={() => {
              setActiveTab("mine");
              setSelectedItem(null);
              setErrorMessage("");
            }}
            role="tab"
            type="button"
          >작성한 리뷰 <span>{myReviews.length}</span></button>
        </div>

        {activeTab === "write" ? <section className="review-write-page__items" aria-label="리뷰 작성 가능 상품">
          {isLoading ? (
            Array.from({ length: 3 }, (_, index) => <Skeleton className="review-write-page__skeleton" key={index} />)
          ) : visibleItems.length > 0 ? (
            visibleItems.map((item) => (
              <button
                className={`review-write-page__item${selectedItem?.order_item_id === item.order_item_id ? " is-selected" : ""}`}
                key={item.order_item_id}
                onClick={() => selectItem(item)}
                type="button"
              >
                <span className="review-write-page__thumbnail">
                  {item.thumbnail_storage_key ? (
                    <img alt="" src={getProductImageUrl(item.thumbnail_storage_key, "w400")} />
                  ) : null}
                </span>
                <span className="review-write-page__item-copy">
                  <small>{item.brand_name}</small>
                  <strong>{item.product_name}</strong>
                  <span>주문번호 {item.order_code}</span>
                </span>
                <span className="review-write-page__select-label">리뷰 작성</span>
              </button>
            ))
          ) : (
            <div className="review-write-page__empty">현재 작성 가능한 리뷰가 없습니다.</div>
          )}
        </section> : (
          <section className="review-write-page__items" aria-label="작성한 리뷰">
            {isLoading ? (
              Array.from({ length: 3 }, (_, index) => <Skeleton className="review-write-page__skeleton" key={index} />)
            ) : myReviews.length > 0 ? (
              myReviews.map((item) => (
                <article className="review-write-page__review" key={item.review.review_id}>
                  <span className="review-write-page__thumbnail">
                    {item.thumbnail_storage_key ? (
                      <img alt="" src={getProductImageUrl(item.thumbnail_storage_key, "w400")} />
                    ) : null}
                  </span>
                  <div className="review-write-page__review-copy">
                    <small>{item.brand_name}</small>
                    <strong>{item.product_name}</strong>
                    <span className="review-write-page__review-rating" aria-label={`${item.review.rating ?? 0}점`}>
                      {"★".repeat(item.review.rating ?? 0)}<i>{"★".repeat(5 - (item.review.rating ?? 0))}</i>
                    </span>
                    <p>{item.review.review_text || "작성한 내용이 없습니다."}</p>
                  </div>
                  <div className="review-write-page__review-actions">
                    {item.review.can_edit ? <button onClick={() => selectReviewToEdit(item)} type="button">수정</button> : null}
                    {item.review.can_delete ? <button onClick={() => setDeleteTarget(item)} type="button">삭제</button> : null}
                  </div>
                </article>
              ))
            ) : (
              <div className="review-write-page__empty">아직 작성한 리뷰가 없습니다.</div>
            )}
          </section>
        )}

        {activeTab === "write" && selectedItem ? (
          <form className="review-write-page__form" onSubmit={submitReview}>
            <h2>{selectedItem.product_name}</h2>
            <fieldset>
              <legend>별점</legend>
              <div className="review-write-page__ratings">
                {[1, 2, 3, 4, 5].map((score) => (
                  <button
                    aria-label={`${score}점`}
                    aria-pressed={rating === score}
                    className={rating >= score ? "is-active" : ""}
                    key={score}
                    onClick={() => setRating(score)}
                    type="button"
                  >
                    ★
                  </button>
                ))}
              </div>
            </fieldset>
            <label>
              <span>리뷰 내용</span>
              <textarea
                maxLength={2000}
                onChange={(event) => setReviewText(event.target.value)}
                placeholder="상품을 사용한 경험을 알려주세요."
                rows={7}
                value={reviewText}
              />
              <small>{reviewText.length} / 2000</small>
            </label>
            <label className="review-write-page__checkbox">
              <input checked={isRepurchase} onChange={(event) => setIsRepurchase(event.target.checked)} type="checkbox" />
              재구매한 상품이에요
            </label>
            {errorMessage ? <p className="review-write-page__error">{errorMessage}</p> : null}
            <div className="review-write-page__actions">
              <button onClick={() => setSelectedItem(null)} type="button">취소</button>
              <button disabled={isSubmitting} type="submit">{isSubmitting ? "등록 중" : "리뷰 등록"}</button>
            </div>
          </form>
        ) : activeTab === "mine" && editingReview ? (
          <form className="review-write-page__form" onSubmit={submitReviewUpdate}>
            <h2>{editingReview.product_name}</h2>
            <fieldset>
              <legend>별점</legend>
              <div className="review-write-page__ratings">
                {[1, 2, 3, 4, 5].map((score) => (
                  <button
                    aria-label={`${score}점`}
                    aria-pressed={rating === score}
                    className={rating >= score ? "is-active" : ""}
                    key={score}
                    onClick={() => setRating(score)}
                    type="button"
                  >★</button>
                ))}
              </div>
            </fieldset>
            <label>
              <span>리뷰 내용</span>
              <textarea
                maxLength={2000}
                onChange={(event) => setReviewText(event.target.value)}
                rows={7}
                value={reviewText}
              />
              <small>{reviewText.length} / 2000</small>
            </label>
            <label className="review-write-page__checkbox">
              <input checked={isRepurchase} onChange={(event) => setIsRepurchase(event.target.checked)} type="checkbox" />
              재구매한 상품이에요
            </label>
            {errorMessage ? <p className="review-write-page__error">{errorMessage}</p> : null}
            <div className="review-write-page__actions">
              <button onClick={() => setEditingReview(null)} type="button">취소</button>
              <button disabled={isSubmitting} type="submit">{isSubmitting ? "저장 중" : "수정 완료"}</button>
            </div>
          </form>
        ) : errorMessage ? (
          <p className="review-write-page__error">{errorMessage}</p>
        ) : null}
      </div>
      <ActivityToast message={toastMessage} />
      <ConfirmModal
        cancelLabel="취소"
        confirmLabel="삭제"
        message="삭제한 리뷰는 되돌릴 수 없습니다. 이 리뷰를 삭제할까요?"
        open={Boolean(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmReviewDelete}
        title="리뷰 삭제"
      />
    </MyPageLayout>
  );
}

export default ReviewWritePage;
