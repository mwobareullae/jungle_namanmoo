import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import { Button } from "../components/ui/button";
import { buttonVariantClassName } from "../components/ui/button-variants";
import { Input } from "../components/ui/input";
import type { AuthUser } from "../contexts/authContextValue";
import { useAuth } from "../contexts/useAuth";
import { API_BASE_URL } from "../lib/api";
import { mergeCart } from "../lib/cartApi";
import { markSkinTestPromptPending } from "../lib/skinTestPrompt";

type LoginLocationState = {
  from?: string;
};

type SocialProvider = "google" | "kakao" | "naver";

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
      }) => void;
      renderButton: (
        parent: HTMLElement,
        options: {
          shape?: "circle" | "pill" | "rectangular" | "square";
          size?: "large" | "medium" | "small";
          theme?: "filled_black" | "filled_blue" | "outline";
          type?: "icon" | "standard";
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

const socialProviderLabels: Record<SocialProvider, string> = {
  google: "구글",
  kakao: "카카오",
  naver: "네이버"
};

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
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleSubmitting, setIsGoogleSubmitting] = useState(false);
  const [isGoogleReady, setIsGoogleReady] = useState(false);
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

      setMessage("로그인 성공!");
      markSkinTestPromptPending();
      navigate(getPostLoginRedirectPath(redirectPath), { replace: true });
    },
    [navigate, redirectPath, refreshAuthenticatedUser, setAuthenticatedUser]
  );

  const handleSocialLogin = (provider: SocialProvider) => {
    setMessage(`${socialProviderLabels[provider]} 간편 로그인은 준비 중입니다.`);
  };

  const handleGoogleCredential = useCallback(
    async (credentialResponse: GoogleCredentialResponse) => {
      if (!credentialResponse.credential) {
        setMessage("Google 로그인 인증 정보를 받지 못했습니다.");
        return;
      }

      setMessage("");
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
            setMessage("Google 이메일 인증이 완료된 계정으로 다시 시도해주세요.");
            return;
          }

          if (errorCode === "INVALID_GOOGLE_TOKEN") {
            setMessage("Google 토큰 검증에 실패했습니다. 백엔드 Google Client ID 설정을 확인해주세요.");
            return;
          }

          if (errorCode === "GOOGLE_LOGIN_NOT_CONFIGURED") {
            setMessage("백엔드 Google 로그인 설정이 아직 완료되지 않았습니다.");
            return;
          }

          if (errorCode === "GOOGLE_AUTH_LIBRARY_NOT_INSTALLED") {
            setMessage("백엔드 Google 인증 라이브러리 설정을 확인해주세요.");
            return;
          }

          setMessage(
            errorCode
              ? `Google 로그인에 실패했습니다. (${errorCode})`
              : "Google 로그인에 실패했습니다. 잠시 후 다시 시도해주세요."
          );
          return;
        }

        await completeLogin(response);
      } catch {
        setMessage("Google 로그인 요청에 실패했습니다. 잠시 후 다시 시도해주세요.");
      } finally {
        setIsGoogleSubmitting(false);
      }
    },
    [completeLogin, navigate]
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
          callback: handleGoogleCredential
        });
        window.google.accounts.id.renderButton(googleButtonRef.current, {
          type: "icon",
          shape: "circle",
          theme: "outline",
          size: "large"
        });
        setIsGoogleReady(true);
      })
      .catch(() => {
        if (isMounted) {
          setIsGoogleReady(false);
          setMessage("Google 로그인 스크립트를 불러오지 못했습니다.");
        }
      });

    return () => {
      isMounted = false;
    };
  }, [handleGoogleCredential]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    if (!isValidEmail(email)) {
      setEmailTouched(true);
      setMessage("");
      return;
    }

    if (password.length === 0) {
      setPasswordTouched(true);
      setMessage("");
      return;
    }

    setMessage("");
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
        setMessage("이메일 또는 비밀번호가 일치하지 않습니다.");
        return;
      }
      await completeLogin(response, { id: 0, email });
    } catch {
      setMessage("로그인 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
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
                    setMessage("");
                  }
                }}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setMessage("");
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
                    setMessage("");
                  }
                }}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setMessage("");
                }}
                placeholder="비밀번호"
                style={{ paddingLeft: "2.75rem", paddingRight: "6rem" }}
                type={showPassword ? "text" : "password"}
                value={password}
              />
              <Button
                className="absolute top-1/2 right-4 -translate-y-1/2 p-0"
                onClick={() => setShowPassword((prev) => !prev)}
                variant="link"
              >
                {showPassword ? "숨김" : "비밀번호 표시"}
              </Button>
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
          {message && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{message}</p>
          )}
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
          <div className="mt-4 flex justify-center gap-3">
            <div className="relative flex h-11 w-11 items-center justify-center">
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 flex h-11 w-11 items-center justify-center rounded-full border border-black/[0.07] bg-white"
              >
                <svg height="20" viewBox="0 0 48 48" width="20">
                  <path
                    d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12
                    c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24
                    c0,11.045,8.955,20,20,20c11.045,0,20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"
                    fill="#FFC107"
                  />
                  <path
                    d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039
                    l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"
                    fill="#FF3D00"
                  />
                  <path
                    d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36
                    c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"
                    fill="#4CAF50"
                  />
                  <path
                    d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571
                    c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"
                    fill="#1976D2"
                  />
                </svg>
              </div>
              <div
                ref={googleButtonRef}
                className={`absolute inset-0 z-20 overflow-hidden rounded-full ${
                  isGoogleSubmitting ? "pointer-events-none opacity-0" : "opacity-0"
                }`}
              />
              {(!googleClientId || !isGoogleReady) && (
                <Button
                  aria-label="구글로 로그인"
                  className="absolute inset-0 z-30"
                  disabled={isGoogleSubmitting}
                  onClick={() => {
                    setMessage(
                      googleClientId
                        ? "Google 로그인 준비 중입니다."
                        : "Google Client ID가 설정되지 않았습니다."
                    );
                  }}
                  variant="icon"
                >
                  <svg height="20" viewBox="0 0 48 48" width="20">
                    <path
                      d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12
                      c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24
                      c0,11.045,8.955,20,20,20c11.045,0,20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"
                      fill="#FFC107"
                    />
                    <path
                      d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039
                      l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"
                      fill="#FF3D00"
                    />
                    <path
                      d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36
                      c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"
                      fill="#4CAF50"
                    />
                    <path
                      d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571
                      c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"
                      fill="#1976D2"
                    />
                  </svg>
                </Button>
              )}
            </div>
            <Button
              aria-label="카카오로 로그인"
              onClick={() => handleSocialLogin("kakao")}
              style={{ backgroundColor: "#fee500", borderColor: "#fee500" }}
              variant="icon"
            >
              <svg height="20" viewBox="0 0 24 24" width="20">
                <path
                  d="M12 4C6.48 4 2 7.48 2 11.8c0 2.77 1.87 5.2 4.68 6.58-.2.75-.73 2.71-.83 3.13-.13.52.19.51.4.37.17-.11 2.66-1.8 3.74-2.53.65.09 1.32.14 2.01.14 5.52 0 10-3.48 10-7.79C22 7.48 17.52 4 12 4z"
                  fill="#000000"
                />
              </svg>
            </Button>
            <Button
              aria-label="네이버로 로그인"
              onClick={() => handleSocialLogin("naver")}
              style={{ backgroundColor: "#03c75a", borderColor: "#03c75a" }}
              variant="icon"
            >
              <svg height="16" viewBox="0 0 20 20" width="16">
                <path d="M11.4 10.6L6.6 4H3v12h4.6V9.4l4.8 6.6H16V4h-4.6v6.6z" fill="#FFFFFF" />
              </svg>
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default LoginPage;
