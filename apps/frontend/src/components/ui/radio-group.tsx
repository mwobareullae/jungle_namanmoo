import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { forwardRef, type ComponentProps, type ElementRef } from "react";

// 순수 pass-through 래퍼. 이 프리미티브를 쓰는 화면(SkinTestQuestionCard)이
// 전부 커스텀 CSS 클래스(styles.css)로 스타일링돼 있어서 Tailwind 스타일을 얹지 않는다.
const RadioGroup = forwardRef<
  ElementRef<typeof RadioGroupPrimitive.Root>,
  ComponentProps<typeof RadioGroupPrimitive.Root>
>(function RadioGroup(props, ref) {
  return <RadioGroupPrimitive.Root ref={ref} {...props} />;
});

function RadioGroupItem(props: ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return <RadioGroupPrimitive.Item {...props} />;
}

export { RadioGroup, RadioGroupItem };
