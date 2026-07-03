import { useState } from "react";
import { Link } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

function PasswordResetPage() {
  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const emailErrorMessage =
    emailTouched && !isValidEmail(email) ? "이메일 형식이 올바르지 않습니다." : "";

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    setMessage("");

    if (!isValidEmail(email)) {
      setEmailTouched(true);
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch("http://localhost:8000/api/auth/password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });

      if (!response.ok) {
        setMessage("비밀번호 재설정 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }

      setMessage("비밀번호 재설정 안내를 이메일로 보냈습니다.");
    } catch {
      setMessage("비밀번호 재설정 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <AuthHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <p className="mb-3 text-[12px] font-semibold text-[#002387]">PASSWORD RESET</p>
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">
              비밀번호 재설정
            </h1>
            <p className="mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
              가입한 이메일을 입력하면 비밀번호 재설정 안내를 보내드릴게요.
            </p>
          </div>
          <form className="grid gap-3" noValidate onSubmit={handleSubmit}>
            <input
              className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                emailErrorMessage
                  ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                  : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
              }`}
              onBlur={() => setEmailTouched(true)}
              onChange={(event) => {
                setEmail(event.target.value);
                setMessage("");
              }}
              placeholder="이메일"
              type="email"
              value={email}
            />
            {emailErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {emailErrorMessage}
              </p>
            )}
            <button
              className="mt-3 w-full cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSubmitting}
              type="submit"
            >
              재설정 링크 받기
            </button>
          </form>
          {message && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{message}</p>
          )}
          <div className="mt-5 text-center">
            <Link
              aria-disabled={isSubmitting}
              className={`text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A] ${
                isSubmitting ? "pointer-events-none opacity-60" : ""
              }`}
              tabIndex={isSubmitting ? -1 : undefined}
              to="/login"
            >
              로그인으로 돌아가기
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}

export default PasswordResetPage;
