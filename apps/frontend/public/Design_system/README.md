# Aqua Glass Design System

뭐바를래 피부 상담 화면을 위한 신규 디자인 시스템입니다.

## Files

- `aqua-glass-design-system.html`: 디자인 시스템 가이드 문서
- `aqua-glass-system.css`: 앱에 적용 가능한 CSS 토큰과 컴포넌트 기본 스타일
- `assets/fonts/ttf`: GmarketSans TTF Light, Medium, Bold
- `assets/fonts/otf`: GmarketSans OTF Light, Medium, Bold
- `assets/images/aqua-shells.png`: 민트 조개 텍스처 레퍼런스
- `assets/images/sea-glass.png`: 해변 유리 텍스처 레퍼런스

## Visual Direction

- Font: GmarketSans
- Mood: transparent, clear, airy, clean
- Image texture: aqua shells, sea glass, pearly mint reflection
- Surface: translucent cards with thin mint-gray borders
- UX: question, choice, input, analysis, recommendation should stay in one continuous flow

## Typography Rules

- Font sizes: `12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48`
- Max display size: `48px`
- Line heights: `120%` for large titles, `140%` for body and supporting copy
- Margins: `16, 20, 24`
- Control heights: `52, 48, 40, 36, 24`
- Font weights: `500` by default, `700` only for rare hero emphasis, avoid `300` in commerce information areas
- Text alignment: left-align by default
- Contrast: target at least `4.5:1` for body text
- Point color: use aqua only for CTA, selected states, and key emphasis

## Commerce Hierarchy

- Section title: `24px / 500 / #222222`
- Section helper: `14px / 500 / #55585D`
- Product name: `14px / 500 / #222222`
- Brand and metadata: `12px / 500 / #737B7A`
- Price: `18px / 500 / #222222`
- Discount and alert: coral only
- Accent color: `#0F6F6A`, limited to CTA, selected state, rank chips, and links

## UX Reference

Referenced: https://uxdesign.kt.com/054231ea3/p/164517-seamless-flow

The guide direction was reflected as a service flow rule: keep the user's context visible and avoid resetting the experience between skin concern input and product recommendation.
