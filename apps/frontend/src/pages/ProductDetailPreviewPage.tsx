import "./ProductDetailPreviewPage.css";
import HomeHeader from "../components/HomeHeader";
import HeartIcon from "../components/ui/HeartIcon";
import ShoppingBagIcon from "../components/ui/ShoppingBagIcon";

const tabs = ["상세정보", "리뷰 5,643", "Q&A 348", "판매자정보", "추천"];

function ProductDetailPreviewPage() {
  return (
    <>
      <HomeHeader />
      <main className="naver-preview-page">

      <section className="naver-preview-product-top">
        <div className="naver-preview-gallery">
          <div className="naver-preview-gallery-main">대표 이미지</div>
        </div>
        <div className="naver-preview-info">
          <h1>상품명이 표시되는 영역입니다. 네이버 상품 상세 제목이 들어갑니다</h1>
          <div className="naver-preview-review-line"><b>★ 4.84</b> (최근 6개월 4.85)　<u>5,643건 리뷰</u></div>
          <div className="naver-preview-info-row"><b>배송</b><span><strong className="green">내일 도착</strong><br />지금 결제 시 내일도착 · 무료배송</span></div>
          <div className="naver-preview-quantity"><b>수량 선택</b><div><button type="button">−</button><span>1</span><button type="button">+</button></div></div>
          <div className="naver-preview-total"><span>총 1개</span><b>총 금액　<strong>199,000원</strong></b></div>
          <div className="naver-preview-buy-grid"><button className="buy" type="button">구매하기</button><button type="button"><HeartIcon size={24} />찜하기</button><button type="button"><ShoppingBagIcon size={24} />장바구니</button></div>
        </div>
      </section>

      <section className="naver-preview-review-strip"><h2>4점 이상 리뷰가 <strong>98%</strong>예요 ⓘ</h2><div>{[1, 2, 3].map((n) => <article key={n}><b>★ {n + 3}</b><p>상품을 사용해본 고객 리뷰가 표시되는 영역입니다...</p></article>)}</div><button type="button">리뷰 전체보기 ›</button></section>
      <div className="naver-preview-promo">지금 시작하면 <strong>웰컴쿠폰</strong> 드려요　멤버십 시작하고 혜택 받기</div>

      <nav className="naver-preview-tabs">{tabs.map((tab, i) => <a className={i === 0 ? 'active' : ''} href={`#preview-${i}`} key={tab}>{tab}</a>)}</nav>
      <section className="naver-preview-detail-layout">
        <div className="naver-preview-detail-main">
          <div className="naver-preview-warning">ⓘ 판매자 안내 및 현금 결제, 개인정보 유도 시 결제/입력하지 마시고 즉시 신고해주세요.</div>
          <article id="preview-0"><h2>상품정보</h2><dl><dt>상품번호</dt><dd>0000000000</dd><dt>제조사</dt><dd>제조사 정보</dd><dt>브랜드</dt><dd>브랜드 정보</dd><dt>배송정보</dt><dd>배송·배송비 무료</dd></dl><div className="naver-preview-detail-placeholder">상세 이미지와 설명이 들어가는 영역</div></article>
          <article id="preview-1"><h2>리뷰</h2><div className="naver-preview-empty">리뷰 목록이 표시되는 영역</div></article>
          <article id="preview-2"><h2>Q&amp;A</h2><div className="naver-preview-empty">상품 문의 목록이 표시되는 영역</div></article>
        </div>
        <aside className="naver-preview-sticky-buy"><p>📍 배송지　<strong>내일 도착</strong></p><div className="naver-preview-quantity"><b>수량 선택</b><div><button type="button">−</button><span>1</span><button type="button">+</button></div></div><div className="naver-preview-total"><span>총 1개</span><b>총 금액　<strong>199,000원</strong></b></div><div className="naver-preview-buy-grid"><button className="buy" type="button">구매하기</button><button type="button"><HeartIcon size={24} />찜</button><button type="button"><ShoppingBagIcon size={24} />장바구니</button></div></aside>
      </section>
      <div className="naver-preview-floating"><button type="button" aria-label="공유">↗</button><button type="button" aria-label="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>↑</button></div>
      </main>
    </>
  );
}

export default ProductDetailPreviewPage;
