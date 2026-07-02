import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";

type LoginResponse = {
  access_token: string;
  refresh_token: string;
  user: {
    id: number;
    email: string;
  };
};

type LoginLocationState = {
  from?: string;
};

const ACCESS_TOKEN_EXPIRES_IN_MS = 15 * 60 * 1000;

const getRedirectPath = (from?: string) => {
  if (!from || !from.startsWith("/") || from.startsWith("//") || from === "/login") {
    return "/";
  }

  return from;
};

function LoginPage() {
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = location.state as LoginLocationState | null;
  const redirectPath = getRedirectPath(locationState?.from);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage("");
    const response = await fetch("http://localhost:8000/api/auth/login", {
      method: "POST",
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
    const data = (await response.json()) as LoginResponse;
    localStorage.setItem("accessToken", data.access_token);
    localStorage.setItem("refreshToken", data.refresh_token);
    localStorage.setItem("authUser", JSON.stringify(data.user));
    localStorage.setItem("accessTokenExpiresAt", String(Date.now() + ACCESS_TOKEN_EXPIRES_IN_MS));
    setMessage("로그인 성공!");
    navigate(redirectPath, { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <AuthHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[520px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">로그인</h1>
          </div>
          <form className="grid gap-3" onSubmit={handleSubmit}>
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
              <input
                className="w-full rounded-[14px] border border-[rgba(0,0,0,0.07)] py-3 pr-4 pl-11 text-[15px] text-[#1A1A1A] focus:border-[rgba(148,224,248,0.44)] focus:outline-none"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="이메일"
                type="email"
                value={email}
              />
            </div>
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
              <input
                className="w-full rounded-[14px] border border-[rgba(0,0,0,0.07)] py-3 pr-14 pl-11 text-[15px] text-[#1A1A1A] focus:border-[rgba(148,224,248,0.44)] focus:outline-none"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="비밀번호"
                type={showPassword ? "text" : "password"}
                value={password}
              />
              <button
                className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer border-0 bg-transparent text-[13px] font-semibold text-[#6B7280] hover:text-[#1A1A1A]"
                onClick={() => setShowPassword((prev) => !prev)}
                type="button"
              >
                {showPassword ? "숨김" : "비밀번호 표시"}
              </button>
            </div>
            <button
              className="mt-3 w-full cursor-pointer rounded-[14px] bg-[#0C1117] py-3.5 text-[15px] font-semibold text-white shadow-[0_2px_24px_rgba(0,0,0,0.06)] hover:bg-[#1A1A1A]"
              type="submit"
            >
              로그인
            </button>
          </form>
          {message && (
            <p className="mt-4 text-center text-sm font-medium text-[#6B7280]">{message}</p>
          )}
          <div className="mt-5 text-center text-[13px] font-medium">
            <a className="text-[#3D3D3D] no-underline hover:underline" href="#">
              비밀번호 재설정
            </a>
            <span className="mx-2.5 text-black/[0.15]">|</span>
            <a className="text-[#3D3D3D] no-underline hover:underline" href="/signup">
              회원가입
            </a>
          </div>
          <div className="mt-7 flex items-center gap-3">
            <div className="h-px flex-1 bg-black/[0.07]" />
            <span className="text-[13px] text-gray-500">간편 로그인</span>
            <div className="h-px flex-1 bg-black/[0.07]" />
          </div>
          <div className="mt-4 flex justify-center gap-3">
            <button
              aria-label="구글로 로그인"
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full border border-black/[0.07] bg-white hover:bg-gray-100"
              type="button"
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
            </button>
            <button
              aria-label="카카오로 로그인"
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full border border-[#fee500] bg-[#fee500] hover:bg-[#fada00]"
              type="button"
            >
              <svg height="20" viewBox="0 0 24 24" width="20">
                <path
                  d="M12 4C6.48 4 2 7.48 2 11.8c0 2.77 1.87 5.2 4.68 6.58-.2.75-.73 2.71-.83 3.13-.13.52.19.51.4.37.17-.11 2.66-1.8 3.74-2.53.65.09 1.32.14 2.01.14 5.52 0 10-3.48 10-7.79C22 7.48 17.52 4 12 4z"
                  fill="#000000"
                />
              </svg>
            </button>
            <button
              aria-label="네이버로 로그인"
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full border border-[#03c75a] bg-[#03c75a] hover:bg-[#02b350]"
              type="button"
            >
              <svg height="16" viewBox="0 0 20 20" width="16">
                <path d="M11.4 10.6L6.6 4H3v12h4.6V9.4l4.8 6.6H16V4h-4.6v6.6z" fill="#FFFFFF" />
              </svg>
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default LoginPage;
