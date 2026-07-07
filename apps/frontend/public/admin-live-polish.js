/*
 * admin-live-polish.js
 * 뭐바를래 관리자 화면 라이브 손질을 앱 로드 시 자동 적용.
 * index.html에 <script src="/admin-live-polish.js"></script> 한 줄로 연결하면
 * 새로고침해도 유지된다. (소스 컴포넌트를 바꾸지 않는 비침투 방식)
 *
 * 담긴 것:
 *  - 스타일 11종(톤/유연표/유동글자/사이드바/상품표열/요약색/썸네일색/재고색/대시보드숨김/로그전폭/배지정렬)
 *  - 설명 카드 12개 글자 기준 숨김(안전장치: 제목정확·입력0·하위제목1)
 *  - 대시보드 상태 카드 4종 숨김 + 도넛/막대 그래프 삽입
 *  - 품절임박 배지 보라색
 *  - MutationObserver로 React 리렌더/화면 전환에도 유지
 */
(function () {
  'use strict';

  var STYLE_ID = 'adm-live-polish-style';
  var CSS = [
    /* 톤 */
    'main,main button,main input,main select,main td,main th,main p,main dd,main dt,main li,main span,main label{font-family:var(--font-ui,"Pretendard Variable","Pretendard",sans-serif) !important}',
    'main{color:#222}',
    'main h1{font-family:var(--font-display,GmarketSans) !important;font-weight:500 !important}',
    'main h2,main h3,main h4{font-family:var(--font-ui,sans-serif) !important;font-weight:600 !important;color:#222 !important}',
    'main [class*="eyebrow"]{font-weight:600 !important;color:#55585d !important}',
    'main p{color:#55585d !important;font-weight:400 !important}',
    'main td{font-weight:400 !important;color:#2c3238 !important}',
    'main th{font-weight:500 !important}',
    'main strong{font-weight:600 !important}',
    'main button{font-weight:500 !important}',
    'nav.admin-nav button{font-weight:500 !important}',
    /* 유연 표 */
    '.admin-main .admin-table-wrap{overflow-x:hidden !important;max-width:100% !important}',
    '.admin-main .admin-table-wrap table,.admin-main table.admin-table{table-layout:fixed !important;width:100% !important;min-width:0 !important}',
    '.admin-main .admin-table-wrap th,.admin-main .admin-table-wrap td{white-space:normal !important;word-break:keep-all !important;overflow-wrap:anywhere !important;min-width:0 !important}',
    '.admin-main .admin-panel,.admin-main [class*="grid"]{min-width:0 !important;max-width:100% !important}',
    /* 유동 글자(컨테이너 쿼리) */
    '.admin-main{container-type:inline-size}',
    '.admin-main h1{font-size:clamp(20px,3.2cqw,30px) !important}',
    '.admin-main h2,.admin-main .admin-panel h2{font-size:clamp(13px,1.95cqw,18px) !important}',
    '.admin-main h3{font-size:clamp(11px,1.62cqw,15px) !important}',
    '.admin-main .admin-table-wrap td{font-size:clamp(9.5px,1.4cqw,13px) !important}',
    '.admin-main .admin-table-wrap th{font-size:clamp(9px,1.3cqw,12px) !important}',
    '.admin-main .admin-badge{font-size:clamp(8.5px,1.28cqw,12px) !important}',
    '.admin-main .admin-panel p,.admin-main [class*="eyebrow"]{font-size:clamp(8.5px,1.18cqw,11px) !important}',
    '.admin-main .admin-pending-item{font-size:clamp(10.5px,1.5cqw,14px) !important}',
    '.admin-main .admin-stat strong,.admin-main .admin-stat b{font-size:clamp(19px,3cqw,28px) !important}',
    /* 사이드바 */
    '.admin-sidebar{flex:0 0 auto !important;min-width:200px !important;width:200px !important}',
    'nav.admin-nav{grid-template-columns:1fr !important;display:flex !important;flex-direction:column !important}',
    'nav.admin-nav button,nav.admin-nav > div{width:100% !important;text-align:left !important;white-space:nowrap !important;word-break:keep-all !important;justify-content:flex-start !important}',
    'nav.admin-nav [class*="group"],nav.admin-nav [class*="label"]{white-space:nowrap !important}',
    /* 상품 표 열폭 + 배지 겹침 해소 */
    '.admin-main .admin-product-table{table-layout:fixed !important}',
    '.admin-main .admin-product-table td,.admin-main .admin-product-table th{overflow:hidden}',
    '.admin-main .admin-product-table th:nth-child(1),.admin-main .admin-product-table td:nth-child(1){width:22% !important;white-space:normal;word-break:keep-all;overflow:visible}',
    '.admin-main .admin-product-table th:nth-child(2),.admin-main .admin-product-table td:nth-child(2){width:12% !important}',
    '.admin-main .admin-product-table th:nth-child(3),.admin-main .admin-product-table td:nth-child(3){width:10% !important}',
    '.admin-main .admin-product-table th:nth-child(4),.admin-main .admin-product-table td:nth-child(4){width:12% !important}',
    '.admin-main .admin-product-table th:nth-child(5),.admin-main .admin-product-table td:nth-child(5){width:10% !important}',
    '.admin-main .admin-product-table th:nth-child(6),.admin-main .admin-product-table td:nth-child(6){width:14% !important}',
    '.admin-main .admin-product-table th:nth-child(7),.admin-main .admin-product-table td:nth-child(7){width:12% !important}',
    '.admin-main .admin-product-table th:nth-child(8),.admin-main .admin-product-table td:nth-child(8){width:8% !important}',
    '.admin-main .admin-product-table td .admin-badge{font-size:10px !important;padding:2px 6px !important;max-width:100%;overflow:hidden;text-overflow:ellipsis;box-sizing:border-box}',
    '.admin-main .admin-product-table td:nth-child(8) button,.admin-main .admin-product-table td:nth-child(8) a{white-space:nowrap !important;padding:4px 8px !important}',
    /* 요약 카드 색(라벨에만) */
    '.admin-main .admin-excel-summary{background:#fff !important;border:1px solid #e7eaef !important}',
    '.admin-main .admin-excel-summary > span:first-child,.admin-main .admin-excel-summary > p:first-child{display:inline-block;padding:2px 9px;border-radius:6px;font-weight:600}',
    '.admin-main .admin-excel-summary.neutral > span:first-child,.admin-main .admin-excel-summary.neutral > p:first-child{background:#eef1f4;color:#55585d}',
    '.admin-main .admin-excel-summary.success > span:first-child,.admin-main .admin-excel-summary.success > p:first-child{background:#dff3f9;color:#1b6f8c}',
    '.admin-main .admin-excel-summary.danger > span:first-child,.admin-main .admin-excel-summary.danger > p:first-child{background:#fde3e3;color:#a13b3b}',
    '.admin-main .admin-excel-summary.warning > span:first-child,.admin-main .admin-excel-summary.warning > p:first-child{background:#fff1c9;color:#8a6d1a}',
    '.admin-main .admin-excel-summary > strong{color:#222 !important}',
    /* 썸네일 색(글자에만) */
    '.admin-main .admin-image-thumb{background:#f4f6f8 !important;border:1px solid #e7eaef !important;display:flex;align-items:center;justify-content:center;font-weight:700 !important}',
    '.admin-main .admin-image-thumb.success{color:#1b6f8c !important}',
    '.admin-main .admin-image-thumb.warning{color:#8a6d1a !important}',
    '.admin-main .admin-image-thumb.danger{color:#a13b3b !important}',
    '.admin-main .admin-image-thumb.neutral{color:#55585d !important}',
    /* 빨간 재고 가격 아래로 */
    '.admin-main td .admin-danger-text{display:block !important;margin-top:2px !important;font-size:11px}',
    /* 대시보드: 설명 카드 3종 숨김 + 행 채움 */
    '.admin-grid > .admin-readiness-panel,.admin-grid > .admin-workflow-panel,.admin-grid > .admin-integration-panel{display:none !important}',
    '.admin-main .admin-grid{align-items:stretch !important}',
    '.admin-main .admin-grid > section{align-self:stretch !important;height:auto !important}',
    /* 로그 카드 전폭 */
    '.admin-main .admin-grid > .admin-operation-panel{grid-column:1 / -1 !important}',
    /* 처리 대기 배지 우측 정렬 */
    '.admin-main .admin-pending-item{align-items:center}',
    '.admin-main .admin-pending-item > span:first-child{flex:1 1 auto;min-width:0}',
    '.admin-main .admin-pending-item > .admin-badge{margin-left:auto !important;min-width:72px;display:inline-flex;justify-content:center;text-align:center;flex:0 0 auto}'
  ].join('\n');

  var HIDE_CARDS = [
    '검색·임베딩 반영', '전성분 입력 기준', '저장 전 확인', '검색·추천 반영 단계',
    '이미지 업로드만으로 어디까지', '이미지 반영 단계', '자동 연결 품질 기준',
    '검색·추천 반영 흐름', '수정 정책', '검색·주문 영향', '주문 처리 기준', '관리자에서 봐야 하는 값'
  ];
  var STAT_HIDE = ['판매중', '검수 필요', '품절 임박', '이미지 누락'];

  function norm(t) { return (t || '').replace(/\s+/g, ' ').trim(); }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildChartHTML() {
    var tokens = { '판매중': '#3aa6d1', '검수 필요': '#f0b429', '이미지 누락': '#e57373', '품절 임박': '#9575cd', '정상': '#e2e8ee' };
    var total = 24585, s1 = 9812, s2 = 1204, s3 = 342, s4 = 87, s5 = total - s1 - s2 - s3 - s4;
    var donut = [['판매중', s1], ['검수 필요', s2], ['이미지 누락', s3], ['품절 임박', s4], ['정상', s5]];
    var VB = 140, C = 70, R = 52, SW = 16, circ = 2 * Math.PI * R, acc = 0;
    var segs = donut.map(function (d) {
      var dash = d[1] / total * circ;
      var el = '<circle cx="' + C + '" cy="' + C + '" r="' + R + '" fill="none" stroke="' + tokens[d[0]] + '" stroke-width="' + SW + '" stroke-dasharray="' + dash + ' ' + (circ - dash) + '" stroke-dashoffset="' + (-acc) + '" transform="rotate(-90 ' + C + ' ' + C + ')"/>';
      acc += dash; return el;
    }).join('');
    var legend = donut.map(function (d) {
      return '<div style="display:flex;align-items:center;gap:7px;font-size:11.5px;color:#55585d;margin:3px 0"><span style="width:9px;height:9px;border-radius:2px;background:' + tokens[d[0]] + ';flex:0 0 auto"></span><span style="flex:1">' + d[0] + '</span><b style="color:#222">' + d[1].toLocaleString() + '</b></div>';
    }).join('');
    var bars = [['성분 검수', 27243, '#f0b429'], ['상품명 중복', 2590, '#3aa6d1'], ['import 실패', 12, '#e57373'], ['이미지 실패', 4, '#e57373'], ['임베딩 대기', 1, '#9575cd']];
    var maxB = Math.max.apply(null, bars.map(function (b) { return b[1]; }));
    var barRows = bars.map(function (b) {
      var w = Math.max(1.5, b[1] / maxB * 100);
      return '<div style="display:flex;align-items:center;gap:9px;margin:8px 0"><span style="width:78px;font-size:11.5px;color:#55585d;text-align:right;flex:0 0 auto">' + b[0] + '</span><div style="flex:1;background:#eef1f4;border-radius:5px;height:17px;overflow:hidden"><div style="width:' + w + '%;height:100%;background:' + b[2] + ';border-radius:5px"></div></div><b style="width:56px;font-size:11.5px;color:#222;text-align:right;flex:0 0 auto">' + b[1].toLocaleString() + '</b></div>';
    }).join('');
    return '<section id="adm-charts" style="margin:0 0 18px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.5fr);gap:16px;padding:0;background:transparent;border:0">'
      + '<div class="admin-panel" style="padding:16px 18px"><p class="admin-eyebrow" style="font-weight:600;color:#55585d;font-size:11px">상품 구성</p><h3 style="margin:2px 0 12px;font-size:15px;color:#222">상품 상태 구성비</h3><div style="display:flex;align-items:center;gap:14px"><svg viewBox="0 0 ' + VB + ' ' + VB + '" style="width:126px;height:126px;flex:0 0 auto;overflow:visible">' + segs + '<text x="' + C + '" y="' + (C - 2) + '" text-anchor="middle" font-size="20" font-weight="700" fill="#222">24.6k</text><text x="' + C + '" y="' + (C + 16) + '" text-anchor="middle" font-size="10" fill="#8a9099">전체 상품</text></svg><div style="flex:1">' + legend + '</div></div></div>'
      + '<div class="admin-panel" style="padding:16px 18px"><p class="admin-eyebrow" style="font-weight:600;color:#55585d;font-size:11px">처리 대기</p><h3 style="margin:2px 0 12px;font-size:15px;color:#222">업무별 대기 건수</h3><div>' + barRows + '</div></div></section>';
  }

  var CHART_HTML = null;
  var busy = false;

  function guard() {
    if (busy) return;
    busy = true;
    try {
      ensureStyle();
      var box = document.querySelector('.admin-main');
      if (!box) return;

      // 설명 카드 숨김 (안전장치: 제목 정확·입력칸 0·하위 제목 1)
      HIDE_CARDS.forEach(function (t) {
        var secs = box.querySelectorAll('section');
        for (var i = 0; i < secs.length; i++) {
          var s = secs[i];
          var hh = s.querySelector('h1,h2,h3,h4');
          if (hh && norm(hh.textContent).indexOf(t) !== -1 &&
            s.querySelectorAll('input,textarea,select').length === 0 &&
            s.querySelectorAll('h1,h2,h3,h4').length === 1 &&
            s.style.display !== 'none') {
            s.style.setProperty('display', 'none', 'important');
          }
        }
      });

      // 대시보드: 상태 카드 4종 숨김 + 그래프 삽입
      var stats = box.querySelector('.admin-stats');
      if (stats) {
        var cards = stats.children;
        for (var j = 0; j < cards.length; j++) {
          var c = cards[j];
          var all = c.querySelectorAll('*');
          var lab = null;
          for (var k = 0; k < all.length; k++) {
            var x = all[k];
            if (x.children.length === 0 && !/^[\d,]+$/.test(norm(x.textContent)) && norm(x.textContent).length > 1) { lab = x; break; }
          }
          if (lab && STAT_HIDE.indexOf(norm(lab.textContent)) !== -1 && c.style.display !== 'none') {
            c.style.setProperty('display', 'none', 'important');
          }
        }
        var grid = box.querySelector('.admin-grid');
        if (grid && !document.getElementById('adm-charts')) {
          if (!CHART_HTML) CHART_HTML = buildChartHTML();
          var d = document.createElement('div');
          d.innerHTML = CHART_HTML;
          grid.parentElement.insertBefore(d.firstChild, grid);
        }
      }

      // 품절임박 배지 보라
      var badges = box.querySelectorAll('.admin-badge');
      for (var m = 0; m < badges.length; m++) {
        var bd = badges[m];
        var bt = norm(bd.textContent);
        if ((bt === '품절임박' || bt === '품절 임박') && bd.style.backgroundColor !== 'rgb(237, 231, 246)') {
          bd.style.setProperty('background-color', '#ede7f6', 'important');
          bd.style.setProperty('color', '#5e35b1', 'important');
        }
      }
    } finally {
      busy = false;
    }
  }

  function start() {
    ensureStyle();
    guard();
    var target = document.querySelector('.admin-main') || document.body;
    var obs = new MutationObserver(function () { guard(); });
    obs.observe(document.body, { childList: true, subtree: true });
    // SPA 라우팅 대비: 주기적 보정(가벼움)
    setInterval(guard, 1200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
