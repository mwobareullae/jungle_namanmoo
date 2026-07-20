import { useEffect, useRef, useState } from "react";

// 옵션이 많은(브랜드/카테고리 등) select 대체용. 네이티브 select 의 "타이핑하면 첫 글자로
// 점프" 기능이 한글 IME 에서는 잘 동작하지 않아, 텍스트로 직접 필터링하는 콤보박스를 쓴다.

export type SearchableSelectOption = {
  code: string;
  name: string;
};

type SearchableSelectProps = {
  options: SearchableSelectOption[];
  value: string;
  onChange: (code: string) => void;
  placeholder: string;
  disabled?: boolean;
  ariaLabel?: string;
  onBlur?: () => void;
};

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder,
  disabled = false,
  ariaLabel,
  onBlur
}: SearchableSelectProps) {
  const selectedOption = options.find((option) => option.code === value) ?? null;
  const [inputValue, setInputValue] = useState(selectedOption?.name ?? "");
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 부모가 value 를 바꾸면(예: 다른 상품 불러오기, 입력값 되돌리기) 표시 텍스트도 맞춘다.
  useEffect(() => {
    void Promise.resolve().then(() => setInputValue(selectedOption?.name ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const filtered =
    inputValue.trim() && inputValue !== selectedOption?.name
      ? options.filter((option) => option.name.toLowerCase().includes(inputValue.trim().toLowerCase()))
      : options;

  const commitSelection = (option: SearchableSelectOption) => {
    onChange(option.code);
    setInputValue(option.name);
    setIsOpen(false);
  };

  const revertToSelection = () => {
    setInputValue(selectedOption?.name ?? "");
    setIsOpen(false);
  };

  return (
    <div className="admin-searchable-select">
      <input
        aria-label={ariaLabel}
        autoComplete="off"
        disabled={disabled}
        onBlur={() => {
          // 옵션 클릭은 onMouseDown 에서 먼저 처리되므로, 여기서는 선택 없이 포커스만
          // 빠져나간 경우(직접 타이핑 후 다른 곳 클릭 등)를 정리한다.
          if (inputValue.trim() === "") {
            onChange("");
          } else if (inputValue !== selectedOption?.name) {
            revertToSelection();
          }
          setIsOpen(false);
          onBlur?.();
        }}
        onChange={(event) => {
          setInputValue(event.target.value);
          setHighlightedIndex(0);
          setIsOpen(true);
        }}
        onFocus={(event) => {
          // 이미 선택된 값이 있는 상태에서 포커스를 받으면 텍스트를 전체 선택해, 바로 타이핑을
          // 시작했을 때 기존 값 뒤에 붙지 않고 덮어써지게 한다(특히 필터용으로 쓸 때 중요).
          event.target.select();
          setIsOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setIsOpen(true);
            setHighlightedIndex((current) => Math.min(current + 1, filtered.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setHighlightedIndex((current) => Math.max(current - 1, 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            const option = filtered[highlightedIndex];
            if (option) commitSelection(option);
          } else if (event.key === "Escape") {
            revertToSelection();
            inputRef.current?.blur();
          }
        }}
        placeholder={placeholder}
        ref={inputRef}
        type="text"
        value={inputValue}
      />
      {isOpen && !disabled && (
        <div className="admin-searchable-select-options" role="listbox">
          {filtered.length === 0 && <div className="admin-searchable-select-empty">검색 결과 없음</div>}
          {filtered.map((option, index) => (
            <div
              className={`admin-searchable-select-option${index === highlightedIndex ? " active" : ""}`}
              key={option.code}
              onMouseDown={(event) => {
                event.preventDefault();
                commitSelection(option);
              }}
              onMouseEnter={() => setHighlightedIndex(index)}
              role="option"
              aria-selected={option.code === value}
            >
              {option.name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
