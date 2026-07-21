import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, EyeSlash } from "@phosphor-icons/react";
import { flushSync } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ActivityToast from "../components/ui/ActivityToast";
import { Button } from "../components/ui/button";
import { buttonVariantClassName } from "../components/ui/button-variants";
import { Input } from "../components/ui/input";
import type { AuthUser } from "../contexts/authContextValue";
import { consumeSessionExpiredFlag } from "../contexts/AuthContext";
import { useAuth } from "../contexts/useAuth";
import { API_BASE_URL } from "../lib/api";
import { mergeCart } from "../lib/cartApi";
import { markSkinTestPromptPending } from "../lib/skinTestPrompt";
import { useActivityToast } from "../hooks/useActivityToast";

type LoginLocationState = {
  from?: string;
};

type LoginResponse = {
  user?: AuthUser;
};

type GoogleCredentialResponse = {
  credential?: string;
};

type GoogleAccounts = {
  accounts?: {
    id?: {
      initialize: (options: {
        client_id: string;
        callback: (response: GoogleCredentialResponse) => void;
        locale?: string;
      }) => void;
      renderButton: (
        parent: HTMLElement,
        options: {
          shape?: "circle" | "pill" | "rectangular" | "square";
          size?: "large" | "medium" | "small";
          text?: "continue_with" | "signin_with" | "signup_with";
          theme?: "filled_black" | "filled_blue" | "outline";
          type?: "icon" | "standard";
          width?: number;
        }
      ) => void;
    };
  };
};

declare global {
  interface Window {
    google?: GoogleAccounts;
  }
}

const LOGIN_EMAIL_FORMAT_ERROR_MESSAGE = "아이디는 이메일 형식으로 입력해주세요.";

const isValidEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const isSignupFlowPath = (value: string) => /^\/signup(?:[/?#]|$)/.test(value);

const getRedirectPath = (from?: string) => {
  if (
    !from ||
    !from.startsWith("/") ||
    from.startsWith("//") ||
    from === "/login" ||
    isSignupFlowPath(from)
  ) {
    return "/";
  }

  return from;
};

const getPostLoginRedirectPath = (redirectPath: string) => {
  if (redirectPath.startsWith("/checkout")) {
    return "/cart";
  }

  return redirectPath;
};

const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim() ?? "";
const googleIdentityScriptSrc = "https://accounts.google.com/gsi/client";
const pendingGoogleCredentialStorageKey = "pending_google_credential";
let googleIdentityScriptPromise: Promise<void> | null = null;

const loadGoogleIdentityScript = () => {
  if (window.google?.accounts?.id) {
    return Promise.resolve();
  }

  if (googleIdentityScriptPromise) {
    return googleIdentityScriptPromise;
  }

  googleIdentityScriptPromise = new Promise<void>((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>(
      `script[src="${googleIdentityScriptSrc}"]`
    );

    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("google script failed")), {
        once: true
      });
      return;
    }

    const script = document.createElement("script");
    script.src = googleIdentityScriptSrc;
    script.async = true;
    script.defer = true;
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener("error", () => reject(new Error("google script failed")), {
      once: true
    });
    document.head.appendChild(script);
  });

  return googleIdentityScriptPromise;
};

function LoginPage() {
  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleSubmitting, setIsGoogleSubmitting] = useState(false);
  const [isGoogleReady, setIsGoogleReady] = useState(false);
  const { message: errorToastMessage, showToast: showErrorToast, clearToast } = useActivityToast(3500);
  const googleButtonRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const { refreshAuthenticatedUser, setAuthenticatedUser } = useAuth();
  const location = useLocation();
  const locationState = location.state as LoginLocationState | null;
  const redirectQuery = new URLSearchParams(location.search).get("redirect") ?? undefined;
  const redirectPath = getRedirectPath(locationState?.from ?? redirectQuery);
  const emailErrorMessage =
    emailTouched && !isValidEmail(email) ? LOGIN_EMAIL_FORMAT_ERROR_MESSAGE : "";
  const passwordErrorMessage = passwordTouched && password.length === 0 ? "비밀번호를 입력해 주세요." : "";

  useEffect(() => {
    if (consumeSessionExpiredFlag()) {
      showErrorToast("세션이 만료되었습니다. 다시 로그인해 주세요.");
    }
  }, [showErrorToast]);

  const completeLogin = useCallback(
    async (response: Response, fallbackUser?: AuthUser) => {
      if (fallbackUser) {
        flushSync(() => setAuthenticatedUser(fallbackUser));
      }

      const data = (await response.json().catch(() => null)) as LoginResponse | null;
      if (data?.user) {
        flushSync(() => setAuthenticatedUser(data.user!));
      } else {
        await refreshAuthenticatedUser().catch(() => null);
      }

      await mergeCart()
        .then(() => window.dispatchEvent(new Event("cart:updated")))
        .catch(() => null);

      clearToast();
      markSkinTestPromptPending();
      navigate(getPostLoginRedirectPath(redirectPath), { replace: true });
    },
    [clearToast, navigate, redirectPath, refreshAuthenticatedUser, setAuthenticatedUser]
  );

  const handleGoogleCredential = useCallback(
    async (credentialResponse: GoogleCredentialResponse) => {
      if (!credentialResponse.credential) {
        showErrorToast("Google 로그인 인증 정보를 받지 못했습니다.");
        return;
      }

      clearToast();
      setIsGoogleSubmitting(true);

      try {
        const response = await fetch(`${API_BASE_URL}/auth/google`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            credential: credentialResponse.credential
          })
        });

        if (!response.ok) {
          const error = (await response.json().catch(() => null)) as {
            code?: string;
            error?: { code?: string };
          } | null;
          const errorCode = error?.code ?? error?.error?.code;

          if (errorCode === "REQUIRED_CONSENT_MISSING") {
            sessionStorage.setItem(
              pendingGoogleCredentialStorageKey,
              credentialResponse.credential
            );
            navigate("/signup?provider=google", { replace: true });
            return;
          }

          if (errorCode === "GOOGLE_EMAIL_NOT_VERIFIED") {
            showErrorToast("Google 이메일 인증이 완료된 계정으로 다시 시도해주세요.");
            return;
          }

          if (errorCode === "INVALID_GOOGLE_TOKEN") {
            showErrorToast("Google 토큰 검증에 실패했습니다. 백엔드 Google Client ID 설정을 확인해주세요.");
            return;
          }

          if (errorCode === "GOOGLE_LOGIN_NOT_CONFIGURED") {
            showErrorToast("백엔드 Google 로그인 설정이 아직 완료되지 않았습니다.");
            return;
          }

          if (errorCode === "GOOGLE_AUTH_LIBRARY_NOT_INSTALLED") {
            showErrorToast("백엔드 Google 인증 라이브러리 설정을 확인해주세요.");
            return;
          }

          showErrorToast(
            errorCode
              ? `Google 로그인에 실패했습니다. (${errorCode})`
              : "Google 로그인에 실패했습니다. 잠시 후 다시 시도해주세요."
          );
          return;
        }

        await completeLogin(response);
      } catch {
        showErrorToast("Google 로그인 요청에 실패했습니다. 잠시 후 다시 시도해주세요.");
      } finally {
        setIsGoogleSubmitting(false);
      }
    },
    [clearToast, completeLogin, navigate, showErrorToast]
  );

  useEffect(() => {
    if (!googleClientId || !googleButtonRef.current) {
      setIsGoogleReady(false);
      return;
    }

    let isMounted = true;

    loadGoogleIdentityScript()
      .then(() => {
        if (!isMounted || !googleButtonRef.current || !window.google?.accounts?.id) {
          return;
        }

        googleButtonRef.current.innerHTML = "";
        window.google.accounts.id.initialize({
          client_id: googleClientId,
          callback: handleGoogleCredential,
          locale: "ko"
        });
        window.google.accounts.id.renderButton(googleButtonRef.current, {
          type: "standard",
          shape: "rectangular",
          theme: "outline",
          size: "large",
          text: "signin_with",
          width: 320
        });
        setIsGoogleReady(true);
      })
      .catch(() => {
        if (isMounted) {
          setIsGoogleReady(false);
          showErrorToast("Google 로그인 스크립트를 불러오지 못했습니다.");
        }
      });

    return () => {
      isMounted = false;
    };
  }, [handleGoogleCredential, showErrorToast]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    if (!isValidEmail(email)) {
      setEmailTouched(true);
      clearToast();
      return;
    }

    if (password.length === 0) {
      setPasswordTouched(true);
      clearToast();
      return;
    }

    clearToast();
    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          email,
          password
        })
      });
      if (!response.ok) {
        const errorBody = await response.json().catch(() => null) as {
          code?: string;
          error?: { code?: string };
        } | null;
        const errorCode = errorBody?.code ?? errorBody?.error?.code;
        if (errorCode === "ACCOUNT_NOT_FOUND") {
          showErrorToast("가입되지 않은 이메일입니다. 이메일을 확인하거나 회원가입해 주세요.");
        } else if (errorCode === "INVALID_PASSWORD") {
          showErrorToast("비밀번호가 일치하지 않습니다. 다시 입력해 주세요.");
        } else if (errorCode === "EMAIL_LOGIN_NOT_AVAILABLE") {
          showErrorToast("소셜 로그인으로 가입한 계정입니다. Google 로그인을 이용해 주세요.");
        } else if (errorCode === "USER_NOT_ACTIVE") {
          showErrorToast("현재 사용할 수 없는 계정입니다. 고객센터에 문의해 주세요.");
        } else {
          showErrorToast("로그인 정보를 확인해 주세요.");
        }
        return;
      }
      await completeLogin(response, { id: 0, email });
    } catch {
      showErrorToast("로그인 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
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
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">로그인</h1>
          </div>
          <form className="grid gap-3" noValidate onSubmit={handleSubmit}>
            <div className="relative">
              <svg
                className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-[#9CA3AF]"
                fill="none"
                height="18"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                viewBox="0 0 24 24"
                width="18"
              >
                <circle cx="12" cy="8" r="4" />
                <path d="M4 20c0-4.4 3.6-8 8-8s8 3.6 8 8" />
              </svg>
              <Input
                invalid={Boolean(emailErrorMessage)}
                onBlur={() => {
                  setEmailTouched(true);
                  if (!isValidEmail(email)) {
                    clearToast();
                  }
                }}
                onChange={(event) => {
                  setEmail(event.target.value);
                  clearToast();
                }}
                placeholder="이메일"
                style={{ paddingLeft: "2.75rem", paddingRight: "1rem" }}
                type="email"
                value={email}
              />
            </div>
            {emailErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {emailErrorMessage}
              </p>
            )}
            <div className="relative">
              <svg
                className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-[#9CA3AF]"
                fill="none"
                height="18"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                viewBox="0 0 24 24"
                width="18"
              >
                <rect height="10" rx="2" width="14" x="5" y="11" />
                <path d="M8 11V7a4 4 0 0 1 8 0v4" />
              </svg>
              <Input
                invalid={Boolean(passwordErrorMessage)}
                onBlur={() => {
                  setPasswordTouched(true);
                  if (password.length === 0) {
                    clearToast();
                  }
                }}
                onChange={(event) => {
                  setPassword(event.target.value);
                  clearToast();
                }}
                placeholder="비밀번호"
                style={{ paddingLeft: "2.75rem", paddingRight: "3rem" }}
                type={showPassword ? "text" : "password"}
                value={password}
              />
              <button
                aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
                aria-pressed={showPassword}
                className="absolute top-1/2 right-4 flex size-8 -translate-y-1/2 items-center justify-center text-[#6B7280] transition-colors hover:text-[#1A1A1A] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1A1A1A]"
                onClick={() => setShowPassword((prev) => !prev)}
                title={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
                type="button"
              >
                {showPassword ? (
                  <EyeSlash aria-hidden="true" size={20} weight="regular" />
                ) : (
                  <Eye aria-hidden="true" size={20} weight="regular" />
                )}
              </button>
            </div>
            {passwordErrorMessage && (
              <p className="-mt-1 px-4 text-[13px] font-medium text-[#ff2b2b]">
                {passwordErrorMessage}
              </p>
            )}
            <Button
              className="mt-3 w-full disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSubmitting}
              type="submit"
            >
              로그인
            </Button>
          </form>
          <div className="mt-5 text-center text-[13px]">
            <Link className={buttonVariantClassName.link} to="/password-reset">
              비밀번호 재설정
            </Link>
            <span className="mx-2.5 text-black/[0.15]">|</span>
            <Link className={buttonVariantClassName.link} to="/signup">
              회원가입
            </Link>
          </div>
          <div className="mt-7 flex items-center gap-3">
            <div className="h-px flex-1 bg-black/[0.07]" />
            <span className="text-[13px] text-gray-500">간편 로그인</span>
            <div className="h-px flex-1 bg-black/[0.07]" />
          </div>
          <div className="mt-4 flex justify-center">
            <div className="relative h-11 w-full max-w-80">
              <div
                ref={googleButtonRef}
                className={`login-google-button h-11 w-full overflow-hidden rounded-sm ${
                  isGoogleSubmitting ? "pointer-events-none opacity-60" : ""
                }`}
              />
              {(!googleClientId || !isGoogleReady) && (
                <Button
                  className="absolute inset-0 z-10 flex h-11 w-full items-center justify-center gap-3"
                  disabled={isGoogleSubmitting}
                  onClick={() => {
                    showErrorToast(
                      googleClientId
                        ? "Google 로그인 준비 중입니다."
                        : "Google Client ID가 설정되지 않았습니다."
                    );
                  }}
                  variant="outline"
                >
                  <svg aria-hidden="true" height="20" viewBox="0 0 48 48" width="20">
                    <path
                      d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
                      fill="#EA4335"
                    />
                    <path
                      d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
                      fill="#4285F4"
                    />
                    <path
                      d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24s.92 7.54 2.56 10.78l7.97-6.19z"
                      fill="#FBBC05"
                    />
                    <path
                      d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
                      fill="#34A853"
                    />
                  </svg>
                  <span>Google 계정으로 로그인</span>
                </Button>
              )}
            </div>
          </div>
        </div>
      </main>
      <ActivityToast message={errorToastMessage} tone="error" />
    </div>
  );
}

export default LoginPage;
