import { type ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";
import SignupProgress from "../components/SignupProgress";
import { privacyPolicy, termsOfService } from "../content/terms";

const SIGNUP_AGREEMENTS_STORAGE_KEY = "signupAgreements";

type TermType = "tos" | "privacy";

const termContent: Record<TermType, { title: string; body: string }> = {
  tos: {
    title: "이용약관",
    body: termsOfService
  },
  privacy: {
    title: "개인정보처리방침",
    body: privacyPolicy
  }
};

const renderInlineContent = (text: string) => {
  const parts = text.split(/(<br>|\*\*[^*]+\*\*|`[^`]+`)/g);

  return parts.map((part, index) => {
    if (part === "<br>") {
      return <br key={`br-${index}`} />;
    }

    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong className="font-semibold text-[#1A1A1A]" key={`strong-${index}`}>
          {part.slice(2, -2)}
        </strong>
      );
    }

    if (part.startsWith("`") && part.endsWith("`")) {
      return <span key={`code-${index}`}>{part.slice(1, -1)}</span>;
    }

    return part;
  });
};

const isTableLine = (line: string) => {
  const trimmedLine = line.trim();

  return trimmedLine.startsWith("|") && trimmedLine.endsWith("|");
};

const isTableDividerLine = (line: string) =>
  /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line.trim());

const parseTableRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

const renderTermBody = (body: string) => {
  let listContext: "none" | "numbered" | "nestedBullet" | "topBullet" = "none";
  const lines = body.split("\n");
  const renderedNodes: ReactNode[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmedLine = line.trim();
    const cleanedLine = line.replace(/^#{1,6}\s+/, "");

    if (trimmedLine === "") {
      listContext = "none";
      renderedNodes.push(<div className="h-3" key={`space-${index}`} />);
      continue;
    }

    if (trimmedLine === "---") {
      listContext = "none";
      renderedNodes.push(<hr className="my-5 border-black/[0.08]" key={`separator-${index}`} />);
      continue;
    }

    if (isTableLine(line)) {
      const tableLines: string[] = [];

      while (index < lines.length && isTableLine(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }

      index -= 1;
      listContext = "none";

      const [headerLine, maybeDividerLine, ...bodyLines] = tableLines;
      const headers = parseTableRow(headerLine);
      const rows = (isTableDividerLine(maybeDividerLine) ? bodyLines : [maybeDividerLine, ...bodyLines])
        .filter(Boolean)
        .map(parseTableRow);

      renderedNodes.push(
        <div
          className="my-4 overflow-x-auto border border-[#E5E7EB] bg-white"
          key={`table-${index}`}
        >
          <table className="min-w-full border-collapse text-left text-[13px] leading-[1.65] text-[#1A1A1A]">
            <thead>
              <tr className="bg-[#CFCFCF]">
                {headers.map((header, headerIndex) => (
                  <th
                    className="border border-[#BDBDBD] px-3 py-2 align-middle font-semibold"
                    key={`table-${index}-header-${headerIndex}`}
                    scope="col"
                  >
                    {renderInlineContent(header)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`table-${index}-row-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td
                      className="border border-[#E5E7EB] px-3 py-2 align-middle"
                      key={`table-${index}-row-${rowIndex}-cell-${cellIndex}`}
                    >
                      {renderInlineContent(row[cellIndex] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (line.startsWith("# ")) {
      listContext = "none";
      renderedNodes.push(
        <p className="text-[18px] leading-[1.5] font-semibold text-[#1A1A1A]" key={`line-${index}`}>
          {renderInlineContent(cleanedLine)}
        </p>
      );
      continue;
    }

    if (line.startsWith("## ")) {
      listContext = "none";
      renderedNodes.push(
        <p className="mt-5 text-[16px] leading-[1.5] font-semibold text-[#1A1A1A]" key={`line-${index}`}>
          {renderInlineContent(cleanedLine)}
        </p>
      );
      continue;
    }

    if (line.startsWith("### ")) {
      listContext = "none";
      renderedNodes.push(
        <p className="mt-4 text-[15px] leading-[1.5] font-semibold text-[#1A1A1A]" key={`line-${index}`}>
          {renderInlineContent(cleanedLine)}
        </p>
      );
      continue;
    }

    if (trimmedLine.startsWith(">")) {
      listContext = "none";
      renderedNodes.push(
        <blockquote
          className="my-4 border-l-4 border-[#D1D5DB] py-1 pl-4 text-[14px] leading-[1.75] font-medium text-[#3D3D3D]"
          key={`quote-${index}`}
        >
          {renderInlineContent(trimmedLine.replace(/^>\s?/, ""))}
        </blockquote>
      );
      continue;
    }

    const numberedListMatch = trimmedLine.match(/^(\d+)\.\s+(.*)$/);

    if (numberedListMatch) {
      const [, number, listText] = numberedListMatch;
      listContext = "numbered";

      renderedNodes.push(
        <div
          className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-1 text-[14px] leading-[1.75] font-medium text-[#3D3D3D]"
          key={`line-${index}`}
        >
          <span className="text-right tabular-nums">{number}.</span>
          <p className="min-w-0 flex-1">{renderInlineContent(listText)}</p>
        </div>
      );
      continue;
    }

    const bulletMatch = line.match(/^(\s*)-\s+(.*)$/);

    if (bulletMatch) {
      const [, , bulletText] = bulletMatch;
      const isNestedBullet: boolean = listContext === "numbered" || listContext === "nestedBullet";
      const indentClassName = isNestedBullet ? "ml-7" : "ml-0";
      listContext = isNestedBullet ? "nestedBullet" : "topBullet";

      renderedNodes.push(
        <div
          className={`${indentClassName} grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-1 text-[14px] leading-[1.75] font-medium text-[#3D3D3D]`}
          key={`line-${index}`}
        >
          <span className="mt-[0.6em] h-1.5 w-1.5 justify-self-center rounded-full bg-[#1A1A1A]" />
          <p className="min-w-0">{renderInlineContent(bulletText)}</p>
        </div>
      );
      continue;
    }

    listContext = "none";

    renderedNodes.push(
      <p className="text-[14px] leading-[1.75] font-medium text-[#3D3D3D]" key={`line-${index}`}>
        {renderInlineContent(cleanedLine)}
      </p>
    );
  }

  return renderedNodes;
};

function SignupTermsPage() {
  const navigate = useNavigate();
  // 체크박스 4개(필수3+선택1)를 각각 true/false로 따로 기억함
  const [agreements, setAgreements] = useState({
    tos: false,
    privacy: false,
    age14: false,
    marketing: false
  });
  // 필수 약관을 체크하지 않았을 때 보여줄 하단 안내 문구
  const [noticeMessage, setNoticeMessage] = useState("");
  const [selectedTerm, setSelectedTerm] = useState<TermType | null>(null);

  // 4개가 전부 true일 때만 true -> "전체 동의" 체크박스 표시에 씀
  const allChecked = Object.values(agreements).every(Boolean);
  const requiredChecked = agreements.tos && agreements.privacy && agreements.age14;

  // "전체 동의" 누르면: 지금 전부 체크돼 있으면 다 해제, 아니면 다 체크
  const handleToggleAll = () => {
    const next = !allChecked;
    setAgreements({ tos: next, privacy: next, age14: next, marketing: next });
  };

  // 체크박스 하나만 콕 집어서 켜고/끄기 (나머지는 안 건드림)
  const handleChange = (key: keyof typeof agreements) => {
    setAgreements((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // "보기" 버튼: 실제 약관 문서는 아직 없어서 선택한 약관만 임시로 기억함
  const handleViewTerm = (term: TermType) => {
    setSelectedTerm(term);
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault(); // 페이지 새로고침 막음
    if (!requiredChecked) {
      setNoticeMessage("필수 약관에 모두 동의해야 다음 단계로 이동할 수 있습니다");
      return;
    }
    // "다음" 화면(정보입력)으로 이동하면서 지금까지 체크한 동의 내용을 같이 들고 감(A방식)
    sessionStorage.setItem(SIGNUP_AGREEMENTS_STORAGE_KEY, JSON.stringify(agreements));
    navigate("/signup/info", { state: { agreements } });
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <AuthHeader />
      <div className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <SignupProgress currentStep={1} />
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">약관 동의</h1>
            <p className="mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
              뭐바를래 이용을 위해 필수 약관을 확인해주세요.
            </p>
          </div>
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <label className="flex cursor-pointer items-center gap-3 rounded-[14px] border border-[rgba(148,224,248,0.44)] bg-[rgba(148,224,248,0.16)] px-4 py-4">
              <input
                checked={allChecked}
                className="h-4 w-4 cursor-pointer accent-[#94e0f8]"
                onChange={handleToggleAll}
                type="checkbox"
              />
              <span className="text-[15px] font-semibold text-[#1A1A1A]">전체 동의합니다</span>
            </label>
            <div className="grid overflow-hidden rounded-[14px] border border-[rgba(0,0,0,0.07)] bg-white">
              <div className="flex items-center justify-between gap-3 border-b border-[rgba(0,0,0,0.07)] px-4 py-4">
                <label className="flex min-w-0 cursor-pointer items-center gap-3">
                  <input
                    checked={agreements.tos}
                    className="h-4 w-4 shrink-0 cursor-pointer accent-[#94e0f8]"
                    onChange={() => handleChange("tos")}
                    type="checkbox"
                  />
                  <span className="text-[14px] font-medium text-[#1A1A1A]">
                    [필수] 이용약관 동의
                  </span>
                </label>
                {/* 실제 문서가 있는 항목이라 "보기" 링크 있음 */}
                <button
                  className="shrink-0 cursor-pointer border-0 bg-transparent text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A]"
                  onClick={() => handleViewTerm("tos")}
                  type="button"
                >
                  보기 &gt;
                </button>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-[rgba(0,0,0,0.07)] px-4 py-4">
                <label className="flex min-w-0 cursor-pointer items-center gap-3">
                  <input
                    checked={agreements.privacy}
                    className="h-4 w-4 shrink-0 cursor-pointer accent-[#94e0f8]"
                    onChange={() => handleChange("privacy")}
                    type="checkbox"
                  />
                  <span className="text-[14px] font-medium text-[#1A1A1A]">
                    [필수] 개인정보처리방침 동의
                  </span>
                </label>
                <button
                  className="shrink-0 cursor-pointer border-0 bg-transparent text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A]"
                  onClick={() => handleViewTerm("privacy")}
                  type="button"
                >
                  보기 &gt;
                </button>
              </div>
              {/* 이 아래 둘은 문서가 따로 없는 자기 확인/동의라 "보기" 링크 없음 */}
              <label className="flex cursor-pointer items-center gap-3 border-b border-[rgba(0,0,0,0.07)] px-4 py-4">
                <input
                  checked={agreements.age14}
                  className="h-4 w-4 shrink-0 cursor-pointer accent-[#94e0f8]"
                  onChange={() => handleChange("age14")}
                  type="checkbox"
                />
                <span className="text-[14px] font-medium text-[#1A1A1A]">
                  [필수] 만 14세 이상입니다
                </span>
              </label>
              <div className="px-4 py-4">
                <label className="flex cursor-pointer items-center gap-3">
                  <input
                    checked={agreements.marketing}
                    className="h-4 w-4 shrink-0 cursor-pointer accent-[#94e0f8]"
                    onChange={() => handleChange("marketing")}
                    type="checkbox"
                  />
                  <span className="text-[14px] font-medium text-[#1A1A1A]">
                    [선택] 마케팅 정보 수신 동의
                  </span>
                </label>
              </div>
            </div>
            <p className="px-1 text-[12px] leading-[1.6] font-medium text-[#9CA3AF]">
              고객은 동의를 거부할 권리가 있으며 동의를 거부할 경우, 사이트 가입 또는 일부 서비스
              이용이 제한됩니다.
            </p>
            <button
              className="mt-2 w-full cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]"
              type="submit"
            >
              다음
            </button>
          </form>
          {noticeMessage && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{noticeMessage}</p>
          )}
        </div>
      </div>
      {selectedTerm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-5 py-8"
          onClick={() => setSelectedTerm(null)}
          role="presentation"
        >
          <div
            aria-modal="true"
            aria-labelledby="terms-modal-title"
            className="flex max-h-[82vh] w-full max-w-[560px] flex-col overflow-hidden rounded-[20px] border border-black/[0.07] bg-white shadow-[0_24px_80px_rgba(0,0,0,0.24)]"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 sm:px-8 sm:pt-8">
              <h2
                className="text-[24px] font-semibold leading-[1.3] text-[#1A1A1A]"
                id="terms-modal-title"
              >
                {termContent[selectedTerm].title}
              </h2>
              <button
                aria-label="약관 모달 닫기"
                className="cursor-pointer border-0 bg-transparent text-[28px] leading-none text-[#6B7280] hover:text-[#1A1A1A]"
                onClick={() => setSelectedTerm(null)}
                type="button"
              >
                ×
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto border-y border-black/[0.07] px-6 py-5 sm:px-8">
              {renderTermBody(termContent[selectedTerm].body)}
            </div>
            <div className="px-6 py-4 sm:px-8">
              <button
                className="w-full cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white hover:bg-[#1A1A1A]"
                onClick={() => setSelectedTerm(null)}
                type="button"
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default SignupTermsPage;
