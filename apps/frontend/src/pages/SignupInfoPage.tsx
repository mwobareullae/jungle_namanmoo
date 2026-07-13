import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import SignupProgress from "../components/SignupProgress";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import type { AuthUser } from "../contexts/authContextValue";
import { useAuth } from "../contexts/useAuth";
import { API_BASE_URL } from "../lib/api";
import { markSkinTestPromptPending } from "../lib/skinTestPrompt";

type SignupErrorResponse = {
  code?: string;
  message?: string;
};

type SignupSuccessResponse = {
  user?: AuthUser;
};

type EmailCheckResponse = {
  available?: boolean;
  code?: string;
  message?: string;
};

type SignupAgreements = {
  tos: boolean;
  privacy: boolean;
  age14: boolean;
  marketing: boolean;
  overseasTransfer: boolean;
};

type EmailCheckState = {
  isChecked: boolean;
  isChecking: boolean;
  status: "idle" | "available" | "unavailable";
  message: string;
};

const SIGNUP_AGREEMENTS_STORAGE_KEY = "signupAgreements";

const initialEmailCheckState: EmailCheckState = {
  isChecked: false,
  isChecking: false,
  status: "idle",
  message: ""
};

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const isValidNickname = (value: string) => value.trim().length > 0;

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

const getStoredSignupAgreements = (): SignupAgreements | null => {
  const rawAgreements = sessionStorage.getItem(SIGNUP_AGREEMENTS_STORAGE_KEY);

  if (!rawAgreements) {
    return null;
  }

  try {
    const parsedAgreements = JSON.parse(rawAgreements) as Partial<SignupAgreements>;

    if (
      parsedAgreements.tos &&
      parsedAgreements.privacy &&
      parsedAgreements.age14 &&
      typeof parsedAgreements.marketing === "boolean" &&
      typeof parsedAgreements.overseasTransfer === "boolean"
    ) {
      return {
        tos: parsedAgreements.tos,
        privacy: parsedAgreements.privacy,
        age14: parsedAgreements.age14,
        marketing: parsedAgreements.marketing,
        overseasTransfer: parsedAgreements.overseasTransfer
      };
    }
  } catch {
    sessionStorage.removeItem(SIGNUP_AGREEMENTS_STORAGE_KEY);
  }

  return null;
};

function SignupInfoPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshAuthenticatedUser, setAuthenticatedUser } = useAuth();
  const agreements = (location.state?.agreements as SignupAgreements | undefined) ?? getStoredSignupAgreements();

  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [emailApiErrorMessage, setEmailApiErrorMessage] = useState("");
  const [emailCheckState, setEmailCheckState] = useState<EmailCheckState>(initialEmailCheckState);
  const [password, setPassword] = useState("");
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [passwordConfirmTouched, setPasswordConfirmTouched] = useState(false);
  const [nickname, setNickname] = useState("");
  const [nicknameTouched, setNicknameTouched] = useState(false);
  const [nicknameApiErrorMessage, setNicknameApiErrorMessage] = useState("");
  const [nicknameCheckState, setNicknameCheckState] = useState<EmailCheckState>(initialEmailCheckState);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const emailErrorMessage =
    emailTouched && !isValidEmail(email)
      ? "이메일 형식이 올바르지 않습니다."
      : emailCheckState.status === "unavailable"
        ? emailCheckState.message
        : emailApiErrorMessage;
  const emailCheckSuccessMessage =
    !emailErrorMessage && emailCheckState.status === "available" ? emailCheckState.message : "";
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
  const nicknameErrorMessage =
    nicknameTouched && !isValidNickname(nickname)
      ? "닉네임을 입력해 주세요."
      : nicknameCheckState.status === "unavailable"
        ? nicknameCheckState.message
        : nicknameApiErrorMessage;
  const nicknameCheckSuccessMessage =
    !nicknameErrorMessage && nicknameCheckState.status === "available" ? nicknameCheckState.message : "";

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

  const handleCheckEmail = async () => {
    if (isSubmitting || emailCheckState.isChecking) {
      return;
    }

    setEmailTouched(true);
    setEmailApiErrorMessage("");
    setErrorMessage("");

    if (!isValidEmail(email)) {
      setEmailCheckState(initialEmailCheckState);
      return;
    }

    setEmailCheckState({
      ...initialEmailCheckState,
      isChecking: true
    });

    try {
      const response = await fetch(
        `${API_BASE_URL}/auth/check-email?email=${encodeURIComponent(email)}`,
        { credentials: "include" }
      );

      if (!response.ok) {
        let error: EmailCheckResponse;

        try {
          error = (await response.json()) as EmailCheckResponse;
        } catch {
          error = {};
        }

        setEmailCheckState({
          isChecked: false,
          isChecking: false,
          status: "unavailable",
          message:
            error.code === "EMAIL_ALREADY_EXISTS" || response.status === 409
              ? "이미 가입된 이메일입니다."
              : "이메일 중복 확인에 실패했습니다."
        });
        return;
      }

      const data = (await response.json()) as EmailCheckResponse;

      if (data.available === false) {
        setEmailCheckState({
          isChecked: false,
          isChecking: false,
          status: "unavailable",
          message: data.message ?? "이미 가입된 이메일입니다."
        });
        return;
      }

      setEmailCheckState({
        isChecked: true,
        isChecking: false,
        status: "available",
        message: "사용 가능한 이메일입니다."
      });
    } catch {
      setEmailCheckState(initialEmailCheckState);
      setEmailApiErrorMessage("이메일 중복 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  const handleCheckNickname = async () => {
    if (isSubmitting || nicknameCheckState.isChecking) {
      return;
    }

    setNicknameTouched(true);
    setNicknameApiErrorMessage("");
    setErrorMessage("");

    if (!isValidNickname(nickname)) {
      setNicknameCheckState(initialEmailCheckState);
      return;
    }

    setNicknameCheckState({
      ...initialEmailCheckState,
      isChecking: true
    });

    try {
      const response = await fetch(
        `${API_BASE_URL}/auth/check-nickname?nickname=${encodeURIComponent(nickname.trim())}`,
        { credentials: "include" }
      );

      if (!response.ok) {
        let error: EmailCheckResponse;

        try {
          error = (await response.json()) as EmailCheckResponse;
        } catch {
          error = {};
        }

        setNicknameCheckState({
          isChecked: false,
          isChecking: false,
          status: "unavailable",
          message:
            error.code === "NICKNAME_ALREADY_EXISTS" || response.status === 409
              ? "이미 사용 중인 닉네임입니다."
              : "닉네임 중복 확인에 실패했습니다."
        });
        return;
      }

      const data = (await response.json()) as EmailCheckResponse;

      if (data.available === false) {
        setNicknameCheckState({
          isChecked: false,
          isChecking: false,
          status: "unavailable",
          message: data.message ?? "이미 사용 중인 닉네임입니다."
        });
        return;
      }

      setNicknameCheckState({
        isChecked: true,
        isChecking: false,
        status: "available",
        message: "사용 가능한 닉네임입니다."
      });
    } catch {
      setNicknameCheckState(initialEmailCheckState);
      setNicknameApiErrorMessage("닉네임 중복 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    if (!isValidEmail(email)) {
      setEmailTouched(true);
      setEmailApiErrorMessage("");
      setErrorMessage("");
      return;
    }

    if (!emailCheckState.isChecked) {
      setEmailTouched(true);
      setEmailApiErrorMessage("이메일 중복 확인을 해주세요.");
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

    if (!isValidNickname(nickname)) {
      setNicknameTouched(true);
      setNicknameApiErrorMessage("");
      setErrorMessage("");
      return;
    }

    if (!nicknameCheckState.isChecked) {
      setNicknameTouched(true);
      setNicknameApiErrorMessage("닉네임 중복 확인을 해주세요.");
      setErrorMessage("");
      return;
    }

    setIsSubmitting(true);

    try {
      let response: Response;

      try {
        response = await fetch(`${API_BASE_URL}/auth/signup`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, nickname: nickname.trim(), consents: agreements })
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
          if (error.code === "NICKNAME_ALREADY_EXISTS") {
            setNicknameTouched(true);
            setNicknameApiErrorMessage("이미 사용 중인 닉네임입니다.");
            setErrorMessage("");
            return;
          }

          setEmailTouched(true);
          setEmailApiErrorMessage("이미 가입된 이메일입니다.");
          setErrorMessage("");
          return;
        }

        setErrorMessage(getSignupErrorMessage(response.status, error.code));
        return;
      }

      sessionStorage.removeItem(SIGNUP_AGREEMENTS_STORAGE_KEY);
      try {
        const signupResult = (await response.json().catch(() => null)) as SignupSuccessResponse | null;
        const nextUser = signupResult?.user ?? await refreshAuthenticatedUser();

        if (!nextUser) {
          setErrorMessage("회원가입은 완료됐지만 로그인 상태 확인에 실패했습니다. 다시 로그인해 주세요.");
          return;
        }
        if (signupResult?.user) {
          setAuthenticatedUser(signupResult.user);
        }
      } catch {
        setErrorMessage("회원가입은 완료됐지만 로그인 상태 확인에 실패했습니다. 다시 로그인해 주세요.");
        return;
      }

      markSkinTestPromptPending();
      navigate("/signup/skin-profile", { replace: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <HomeHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <SignupProgress currentStep={2} />
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">정보 입력</h1>
            <p className="mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
              로그인에 사용할 이메일과 비밀번호를 입력해주세요.
            </p>
          </div>
          <form className="grid gap-3" noValidate onSubmit={handleSubmit}>
            <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
              <Input
                invalid={Boolean(emailErrorMessage)}
                onBlur={() => {
                  setEmailTouched(true);
                  if (!isValidEmail(email)) {
                    setErrorMessage("");
                  }
                }}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setEmailApiErrorMessage("");
                  setEmailCheckState(initialEmailCheckState);
                  setErrorMessage("");
                }}
                placeholder="이메일"
                type="email"
                value={email}
              />
              <Button
                className="px-3 py-3 text-[14px] disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isSubmitting || emailCheckState.isChecking}
                onClick={handleCheckEmail}
                variant="outline"
              >
                중복 확인
              </Button>
            </div>
            {emailErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {emailErrorMessage}
              </p>
            )}
            {emailCheckSuccessMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#3D6B4F]">
                {emailCheckSuccessMessage}
              </p>
            )}
            <Input
              invalid={Boolean(passwordErrorMessage)}
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
            <Input
              invalid={Boolean(passwordConfirmErrorMessage)}
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
            <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
              <Input
                invalid={Boolean(nicknameErrorMessage)}
                onBlur={() => {
                  setNicknameTouched(true);
                  if (!isValidNickname(nickname)) {
                    setErrorMessage("");
                  }
                }}
                onChange={(e) => {
                  setNickname(e.target.value);
                  setNicknameApiErrorMessage("");
                  setNicknameCheckState(initialEmailCheckState);
                  setErrorMessage("");
                }}
                placeholder="닉네임"
                type="text"
                value={nickname}
              />
              <Button
                className="px-3 py-3 text-[14px] disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isSubmitting || nicknameCheckState.isChecking}
                onClick={handleCheckNickname}
                variant="outline"
              >
                중복 확인
              </Button>
            </div>
            {nicknameErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {nicknameErrorMessage}
              </p>
            )}
            {nicknameCheckSuccessMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#3D6B4F]">
                {nicknameCheckSuccessMessage}
              </p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Button
                className="disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isSubmitting}
                onClick={() => navigate("/signup")}
                variant="outline"
              >
                이전으로
              </Button>
              <Button
                className="disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                type="submit"
              >
                가입 완료
              </Button>
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
