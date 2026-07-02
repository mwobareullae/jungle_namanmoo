import { useState } from "react";

function LoginPage() {
  const [message, setMessage] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const response = await fetch("http://localhost:8000/api/auth/login", {
      method: "POST",
    });
    if (response.ok) {
      setMessage("로그인 성공!");
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#fafafa]">
      <header className="px-6 py-5">
        <a className="text-xl font-bold text-[#1a1a1a] no-underline" href="/">
          뭐바를래
        </a>
      </header>
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-[400px] rounded-[20px] bg-white px-8 py-10 shadow-[0_2px_24px_rgba(0,0,0,0.06)]">
          <h1 className="mb-6 text-center text-2xl font-bold text-[#1a1a1a]">로그인</h1>
          <form onSubmit={handleSubmit}>
            <div className="relative mb-3">
              <svg
                className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-gray-500"
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
                className="w-full rounded-lg border border-black/[0.07] py-3 pr-4 pl-10 text-[15px] text-[#1a1a1a] focus:border-[#3d3d3d] focus:outline-none"
                placeholder="아이디"
                type="text"
              />
            </div>
            <div className="relative mb-3">
              <svg
                className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-gray-500"
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
                className="w-full rounded-lg border border-black/[0.07] py-3 pr-14 pl-10 text-[15px] text-[#1a1a1a] focus:border-[#3d3d3d] focus:outline-none"
                placeholder="비밀번호"
                type={showPassword ? "text" : "password"}
              />
              <button
                className="absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer border-0 bg-transparent text-[13px] text-[#3d3d3d]"
                onClick={() => setShowPassword((prev) => !prev)}
                type="button"
              >
                {showPassword ? "숨김" : "표시"}
              </button>
            </div>
            <button
              className="w-full cursor-pointer rounded-lg bg-[#1a1a1a] py-3.5 text-[15px] font-bold text-white hover:bg-[#3d3d3d]"
              type="submit"
            >
              로그인
            </button>
          </form>
          {message && <p className="mt-4 text-center text-sm text-[#3d3d3d]">{message}</p>}
          <div className="mt-5 text-center text-[13px]">
            <a className="text-[#3d3d3d] no-underline hover:underline" href="#">
              아이디 찾기
            </a>
            <span className="mx-2.5 text-black/[0.15]">|</span>
            <a className="text-[#3d3d3d] no-underline hover:underline" href="#">
              비밀번호 재설정
            </a>
            <span className="mx-2.5 text-black/[0.15]">|</span>
            <a className="text-[#3d3d3d] no-underline hover:underline" href="/signup">
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
      </div>
    </div>
  );
}

export default LoginPage;
