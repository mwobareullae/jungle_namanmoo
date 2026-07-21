-- M3-C 이미지 대량 연결 통합 QA 전용 정리 스크립트.
-- 실행 전/후 QA_M3C_ 접두어 대상만 확인한다. 실제 운영 상품에는 사용하지 않는다.
-- ES 문서 삭제는 이 SQL 다음에 `sync_catalog_product_after_commit` 호출로 별도 수행한다.

begin;

create temp table qa_m3c_product_ids on commit drop as
select id
from products
where import_sku like 'QA_M3C_%';

delete from recent_views
where product_id in (select id from qa_m3c_product_ids);

delete from product_images
where product_id in (select id from qa_m3c_product_ids);

delete from inventories
where product_id in (select id from qa_m3c_product_ids);

delete from product_prices
where product_id in (select id from qa_m3c_product_ids);

delete from products
where id in (select id from qa_m3c_product_ids);

commit;
