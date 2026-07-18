\set ON_ERROR_STOP on

\if :{?qa_run_prefix}
\else
  \echo 'ERROR: qa_run_prefix is required. Example: QA_M3B_20260718_RUN01_%'
  \quit
\endif

\echo Cleaning M3-B QA artifacts for prefix :qa_run_prefix

BEGIN;

-- QA가 모두 끝난 뒤, 아직 product_ingredients가 남아 있을 때 이번 실행의 대상만 캡처한다.
CREATE TEMP TABLE qa_product_ids ON COMMIT DROP AS
SELECT id
FROM products
WHERE import_sku LIKE :'qa_run_prefix';

CREATE TEMP TABLE qa_pending_ids ON COMMIT DROP AS
SELECT DISTINCT pi.ingredient_id
FROM product_ingredients pi
JOIN ingredients i ON i.id = pi.ingredient_id
WHERE pi.product_id IN (SELECT id FROM qa_product_ids)
  AND i.ingredient_code LIKE 'ing_pending_admin_%';

CREATE TEMP TABLE qa_review_ids ON COMMIT DROP AS
SELECT id
FROM ingredient_mapping_reviews
WHERE source_ingredient_id IN (SELECT ingredient_id FROM qa_pending_ids);

SELECT 'qa_products' AS item, count(*) AS count FROM qa_product_ids
UNION ALL
SELECT 'qa_pending_ingredients', count(*) FROM qa_pending_ids
UNION ALL
SELECT 'qa_mapping_reviews', count(*) FROM qa_review_ids;

-- review event는 review·ingredient를 모두 참조한다.
DELETE FROM ingredient_mapping_review_events event
USING qa_review_ids review_id
WHERE event.review_id = review_id.id;

DELETE FROM ingredient_mapping_reviews review
USING qa_review_ids review_id
WHERE review.id = review_id.id;

-- products 하위의 실제 FK 그래프를 깊은 순서부터 정리한다.
DELETE FROM product_review_profile_labels label
USING product_reviews review
WHERE label.review_id = review.id
  AND (
    review.product_id IN (SELECT id FROM qa_product_ids)
    OR review.order_item_id IN (
      SELECT id FROM order_items WHERE product_id IN (SELECT id FROM qa_product_ids)
    )
  );

DELETE FROM order_claim_items claim_item
USING order_items order_item
WHERE claim_item.order_item_id = order_item.id
  AND order_item.product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM recommendation_score_evidence evidence
USING recommendation_results result
WHERE evidence.recommendation_result_id = result.id
  AND result.product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_reviews
WHERE product_id IN (SELECT id FROM qa_product_ids)
   OR order_item_id IN (
     SELECT id FROM order_items WHERE product_id IN (SELECT id FROM qa_product_ids)
   );

DELETE FROM order_items
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM cart_items
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM inventory_movements
WHERE product_id IN (SELECT id FROM qa_product_ids)
   OR inventory_id IN (
     SELECT id FROM inventories WHERE product_id IN (SELECT id FROM qa_product_ids)
   );

DELETE FROM product_effect_recommendation_features
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_images
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_ingredients
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_popularity_metrics
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_prices
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_recommendation_coarse_features
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_recommendation_features
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_recommendation_scoring_read_models
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_recommendation_scoring_snapshots
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_review_metrics
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_review_segment_metrics
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM product_skin_profiles
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM recent_views
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM recommendation_results
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM search_candidates
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM search_documents
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM wishlists
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM inventories
WHERE product_id IN (SELECT id FROM qa_product_ids);

DELETE FROM products
WHERE id IN (SELECT id FROM qa_product_ids);

-- 이번 QA가 만든 pending만, 다른 상품·판정이 더 이상 참조하지 않을 때 삭제한다.
DELETE FROM ingredients ingredient
WHERE ingredient.id IN (SELECT ingredient_id FROM qa_pending_ids)
  AND NOT EXISTS (
    SELECT 1 FROM product_ingredients pi WHERE pi.ingredient_id = ingredient.id
  )
  AND NOT EXISTS (
    SELECT 1 FROM ingredient_mapping_reviews review
    WHERE review.source_ingredient_id = ingredient.id
       OR review.target_ingredient_id = ingredient.id
  );

COMMIT;

-- CONCURRENTLY는 transaction 밖에서만 실행 가능하다.
REFRESH MATERIALIZED VIEW CONCURRENTLY ingredient_mapping_pending_groups;

SELECT
  (SELECT count(*) FROM products WHERE import_sku IS NOT NULL) AS import_sku_products,
  (SELECT count(*) FROM ingredients WHERE ingredient_code LIKE 'ing_pending_admin_%') AS admin_pending_ingredients,
  (SELECT count(*) FROM ingredient_mapping_reviews) AS mapping_reviews,
  (SELECT count(*) FROM ingredient_mapping_review_events) AS mapping_review_events;
