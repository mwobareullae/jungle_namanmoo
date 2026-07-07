import { useState } from "react";
import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import { API_BASE_URL } from "../lib/api";

type PasswordResetStep = "request" | "confirm" | "complete";

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const isValidResetCode = (value: string) => /^\d{6}$/.test(value);
const isValidPassword = (value: string) => /^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(value);

function PasswordResetPage() {
  const [step, setStep] = useState<PasswordResetStep>("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [codeTouched, setCodeTouched] = useState(false);
  const [newPasswordTouched, setNewPasswordTouched] = useState(false);
  const [newPasswordConfirmTouched, setNewPasswordConfirmTouched] = useState(false);
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const emailErrorMessage =
    emailTouched && !isValidEmail(email) ? "이메일 형식이 올바르지 않습니다." : "";
  const codeErrorMessage =
    codeTouched && !isValidResetCode(code) ? "인증 코드는 6자리 숫자로 입력해주세요." : "";
  const newPasswordErrorMessage =
    newPasswordTouched && !isValidPassword(newPassword)
      ? "비밀번호는 8자 이상, 영문 + 숫자를 포함해야 합니다."
      : "";
  const newPasswordConfirmErrorMessage =
    newPasswordConfirmTouched && newPassword !== newPasswordConfirm
      ? "비밀번호가 일치하지 않습니다."
      : "";

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
      const response = await fetch(`${API_BASE_URL}/auth/password-reset`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });

      if (!response.ok) {
        setMessage("비밀번호 재설정 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }

      setStep("confirm");
      setMessage("인증 코드를 이메일로 보냈습니다.");
    } catch {
      setMessage("비밀번호 재설정 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    setMessage("");
    setCodeTouched(true);
    setNewPasswordTouched(true);
    setNewPasswordConfirmTouched(true);

    if (
      !isValidResetCode(code) ||
      !isValidPassword(newPassword) ||
      newPassword !== newPasswordConfirm
    ) {
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE_URL}/auth/password-reset/confirm`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          code,
          new_password: newPassword
        })
      });

      if (!response.ok) {
        setMessage("인증 코드가 올바르지 않거나 만료되었습니다.");
        return;
      }

      setStep("complete");
      setMessage("");
    } catch {
      setMessage("비밀번호 변경에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <HomeHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div
          className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10"
          data-step={step}
        >
          <div className="mb-7">
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">
              비밀번호 재설정
            </h1>
            {step === "request" && (
              <p className="password-reset-request-copy mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
                가입한 이메일을 입력하면 비밀번호 재설정 안내를 보내드릴게요.
              </p>
            )}
          </div>
          {step === "request" && (
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
          )}
          {step === "confirm" && (
            <form className="grid gap-3" noValidate onSubmit={handleConfirmSubmit}>
              <input
                className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                  codeErrorMessage
                    ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                    : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
                }`}
                inputMode="numeric"
                maxLength={6}
                onBlur={() => setCodeTouched(true)}
                onChange={(event) => {
                  setCode(event.target.value);
                  setMessage("");
                }}
                placeholder="인증 코드 6자리"
                value={code}
              />
              {codeErrorMessage && (
                <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                  {codeErrorMessage}
                </p>
              )}
              <input
                className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                  newPasswordErrorMessage
                    ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                    : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
                }`}
                onBlur={() => setNewPasswordTouched(true)}
                onChange={(event) => {
                  setNewPassword(event.target.value);
                  setMessage("");
                }}
                placeholder="새 비밀번호"
                type="password"
                value={newPassword}
              />
              {newPasswordErrorMessage && (
                <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                  {newPasswordErrorMessage}
                </p>
              )}
              <input
                className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                  newPasswordConfirmErrorMessage
                    ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                    : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
                }`}
                onBlur={() => setNewPasswordConfirmTouched(true)}
                onChange={(event) => {
                  setNewPasswordConfirm(event.target.value);
                  setMessage("");
                }}
                placeholder="새 비밀번호 확인"
                type="password"
                value={newPasswordConfirm}
              />
              {newPasswordConfirmErrorMessage && (
                <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                  {newPasswordConfirmErrorMessage}
                </p>
              )}
              <button
                className="mt-3 w-full cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                type="submit"
              >
                비밀번호 변경
              </button>
            </form>
          )}
          {step === "complete" && (
            <div className="grid gap-3">
              <div className="rounded-[16px] border border-[rgba(148,224,248,0.55)] bg-[rgba(148,224,248,0.16)] px-5 py-6 text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#94E0F8] text-[20px] font-semibold text-[#063445]">
                  ✓
                </div>
                <p className="text-[17px] font-semibold text-[#1A1A1A]">
                  비밀번호 변경이 완료되었습니다.
                </p>
                <p className="mt-2 text-[14px] leading-[1.6] font-medium text-[#3D3D3D]">
                  새 비밀번호로 다시 로그인해 주세요.
                </p>
              </div>
              <Link
                className="mt-3 w-full rounded-[14px] bg-[#0C1117] py-3.5 text-center text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]"
                to="/login"
              >
                로그인으로 돌아가기
              </Link>
            </div>
          )}
          {message && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{message}</p>
          )}
          {step !== "complete" && (
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
          )}
        </div>
      </main>
    </div>
  );
}

export default PasswordResetPage;
