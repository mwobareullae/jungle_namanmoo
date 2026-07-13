import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";

const steps = [
  ["1. 접수", "마이페이지 > 주문/배송내역에서 주문을 선택한 뒤 반품·교환을 신청합니다."],
  ["2. 확인", "상품 상태와 사유를 확인한 뒤 회수 방법과 배송비를 안내합니다."],
  ["3. 회수", "안내받은 방법으로 상품을 포장해 보내주세요."],
  ["4. 처리", "상품 확인 후 교환 발송 또는 환불을 진행합니다."]
] as const;

function ReturnPolicyPage() {
  return (
    <div className="category-page return-policy-page">
      <HomeHeader />
      <main className="category-page__main return-policy-page__main">
        <nav className="category-page__breadcrumb" aria-label="반품 교환 환불 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>반품·교환·환불</span>
        </nav>
        <h1 className="category-page__title">반품·교환·환불</h1>
        <p className="return-policy-page__intro">
          주문 상품에 문제가 있거나 단순 변심으로 반품·교환이 필요한 경우 아래 기준을 확인해 주세요.
        </p>

        <div className="return-policy-page__content">
          <section className="return-policy-card">
            <h2>신청 절차</h2>
            <div className="return-policy-steps">
              {steps.map(([title, description]) => (
                <div className="return-policy-step" key={title}>
                  <strong>{title}</strong>
                  <p>{description}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="return-policy-card">
            <h2>신청 가능 기간</h2>
            <ul>
              <li>단순 변심: 상품 수령 후 7일 이내</li>
              <li>상품 하자·오배송: 상품 수령 후 30일 이내 또는 사실을 안 날부터 30일 이내</li>
              <li>신청 전 상품의 사용·훼손 여부와 구성품을 확인해 주세요.</li>
            </ul>
          </section>

          <section className="return-policy-card return-policy-card--notice">
            <h2>반품·교환이 어려운 경우</h2>
            <ul>
              <li>사용 또는 세척으로 상품 가치가 크게 떨어진 경우</li>
              <li>포장, 구성품, 사은품이 누락되거나 훼손된 경우</li>
              <li>시간이 지나 재판매가 곤란한 상품인 경우</li>
              <li>맞춤 제작·위생 상품 등 상품 상세 페이지에 별도 안내된 경우</li>
            </ul>
          </section>

          <section className="return-policy-card">
            <h2>배송비와 환불</h2>
            <ul>
              <li>단순 변심에 의한 반품·교환은 고객 부담으로 처리될 수 있습니다.</li>
              <li>상품 하자·오배송은 확인 후 배송비를 판매자가 부담합니다.</li>
              <li>환불은 반품 상품 확인 후 결제 수단에 따라 순차적으로 진행됩니다.</li>
              <li>카드사·결제 수단에 따라 실제 환불 반영 시점은 달라질 수 있습니다.</li>
            </ul>
          </section>
        </div>

        <p className="return-policy-page__contact">
          주문 상태나 상품별 정책 확인이 필요하면 <Link to="/mypage/orders">주문/배송내역</Link>에서 주문을 선택해 문의해 주세요.
        </p>
      </main>
    </div>
  );
}

export default ReturnPolicyPage;
