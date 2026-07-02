import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";

type SignupResponse = {
  access_token: string;
  refresh_token: string;
  user: {
    id: number;
    email: string;
    created_at?: string;
  };
};

type SignupErrorResponse = {
  code?: string;
  message?: string;
};

const ACCESS_TOKEN_EXPIRES_IN_MS = 15 * 60 * 1000;

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

// API 스펙 조건: 8자 이상, 영문+숫자 포함
const isValidPassword = (password: string) =>
  password.length >= 8 && /[a-zA-Z]/.test(password) && /[0-9]/.test(password);

const getSignupErrorMessage = (status: number, code?: string) => {
  if (code === "EMAIL_ALREADY_EXISTS" || status === 409) {
    return "이미 가입된 이메일입니다.";
  }

  if (status >= 500) {
    return "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }

  return "회원가입에 실패했습니다. 잠시 후 다시 시도해 주세요.";
};

function SignupInfoPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const agreements = location.state?.agreements;

  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [emailApiErrorMessage, setEmailApiErrorMessage] = useState("");
  const [password, setPassword] = useState("");
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [passwordConfirmTouched, setPasswordConfirmTouched] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const emailErrorMessage =
    emailTouched && !isValidEmail(email)
      ? "이메일 형식이 올바르지 않습니다."
      : emailApiErrorMessage;
  const passwordErrorMessage =
    passwordTouched && !isValidPassword(password)
      ? "비밀번호는 8자 이상, 영문 + 숫자를 포함해야 합니다."
      : "";
  const passwordConfirmErrorMessage =
    (passwordConfirmTouched || passwordTouched) &&
    isValidPassword(password) &&
    passwordConfirm.length > 0 &&
    password !== passwordConfirm
      ? "비밀번호가 일치하지 않습니다."
      : "";

  // 약관 동의 없이 바로 들어왔으면 약관 동의 화면으로 돌려보냄
  useEffect(() => {
    if (!agreements) {
      navigate("/signup", { replace: true });
    }
  }, [agreements, navigate]);

  // 돌려보내지는 동안(리다이렉트 되기 직전)에는 화면에 아무것도 안 보여줌
  if (!agreements) {
    return null;
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!isValidEmail(email)) {
      setEmailTouched(true);
      setEmailApiErrorMessage("");
      setErrorMessage("");
      return;
    }

    if (!isValidPassword(password)) {
      setPasswordTouched(true);
      setErrorMessage("");
      return;
    }

    if (password !== passwordConfirm) {
      setPasswordConfirmTouched(true);
      setErrorMessage("");
      return;
    }

    let response: Response;

    try {
      response = await fetch("http://localhost:8000/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, consents: agreements })
      });
    } catch {
      setErrorMessage("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      return;
    }

    if (!response.ok) {
      let error: SignupErrorResponse;

      try {
        error = (await response.json()) as SignupErrorResponse;
      } catch {
        error = {};
      }

      if (error.code === "EMAIL_ALREADY_EXISTS" || response.status === 409) {
        setEmailTouched(true);
        setEmailApiErrorMessage("이미 가입된 이메일입니다.");
        setErrorMessage("");
        return;
      }

      setErrorMessage(getSignupErrorMessage(response.status, error.code));
      return;
    }

    const data = (await response.json()) as SignupResponse;
    localStorage.setItem("accessToken", data.access_token);
    localStorage.setItem("refreshToken", data.refresh_token);
    localStorage.setItem("authUser", JSON.stringify(data.user));
    localStorage.setItem("accessTokenExpiresAt", String(Date.now() + ACCESS_TOKEN_EXPIRES_IN_MS));
    setErrorMessage("가입 완료!");
    navigate("/", { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <AuthHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <p className="mb-3 text-[12px] font-semibold text-[#002387]">SIGN UP 2 / 2</p>
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">정보 입력</h1>
            <p className="mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
              로그인에 사용할 이메일과 비밀번호를 입력해주세요.
            </p>
          </div>
          <form className="grid gap-3" noValidate onSubmit={handleSubmit}>
            <input
              className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                emailErrorMessage
                  ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                  : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
              }`}
              onBlur={() => {
                setEmailTouched(true);
                if (!isValidEmail(email)) {
                  setErrorMessage("");
                }
              }}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailApiErrorMessage("");
                setErrorMessage("");
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
            <input
              className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                passwordErrorMessage
                  ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                  : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
              }`}
              onBlur={() => {
                setPasswordTouched(true);
                if (!isValidPassword(password)) {
                  setErrorMessage("");
                }
              }}
              onChange={(e) => {
                setPassword(e.target.value);
                setErrorMessage("");
              }}
              placeholder="비밀번호 (8자 이상, 영문+숫자)"
              type="password"
              value={password}
            />
            {passwordErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {passwordErrorMessage}
              </p>
            )}
            <input
              className={`w-full rounded-[14px] border px-4 py-3 text-[15px] text-[#1A1A1A] focus:outline-none ${
                passwordConfirmErrorMessage
                  ? "border-[#ff2b2b] focus:border-[#ff2b2b]"
                  : "border-[rgba(0,0,0,0.07)] focus:border-[rgba(148,224,248,0.44)]"
              }`}
              onBlur={() => {
                setPasswordConfirmTouched(true);
                if (
                  isValidPassword(password) &&
                  passwordConfirm.length > 0 &&
                  password !== passwordConfirm
                ) {
                  setErrorMessage("");
                }
              }}
              onChange={(e) => {
                setPasswordConfirm(e.target.value);
                setErrorMessage("");
              }}
              placeholder="비밀번호 확인"
              type="password"
              value={passwordConfirm}
            />
            {passwordConfirmErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {passwordConfirmErrorMessage}
              </p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-3">
              <button
                className="cursor-pointer rounded-[14px] border border-[rgba(0,0,0,0.07)] bg-white py-3.5 text-[15px] font-semibold text-[#3D3D3D] hover:bg-[#FAFAFA]"
                onClick={() => navigate("/signup")}
                type="button"
              >
                이전으로
              </button>
              <button
                className="cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]"
                type="submit"
              >
                가입 완료
              </button>
            </div>
          </form>
          {errorMessage && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{errorMessage}</p>
          )}
        </div>
      </main>
    </div>
  );
}

export default SignupInfoPage;
