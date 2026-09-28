// 화면 1: 로그인 / 회원가입 — 한 화면에서 탭으로 전환(SPEC §8.1).
// 가입하면 캐릭터 2개(국내·해외)에 각 1억원이 지급된다는 안내를 가입 탭에 고정한다.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api";
import { useSession } from "../session";
import "../components/theme.css";
import "../components/app.css";

type Tab = "login" | "signup";

const MIN_PASSWORD = 10;

export function Login() {
  const [tab, setTab] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { refresh, setMe } = useSession();
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // 서버도 검사하지만, 왕복 한 번을 아끼고 즉시 이유를 알려준다.
    if (!email.includes("@")) return setError("이메일 형식이 아닙니다.");
    if (password.length < MIN_PASSWORD) {
      return setError(`비밀번호는 ${MIN_PASSWORD}자 이상이어야 합니다.`);
    }
    if (tab === "signup" && nickname.trim().length === 0) {
      return setError("어떻게 불러드릴지 별명을 적어주세요.");
    }

    setBusy(true);
    try {
      const user =
        tab === "signup"
          ? await api.signup({ email, password, nickname: nickname.trim() })
          : await api.login({ email, password });
      setMe(user);
      await refresh();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "잠시 후 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <h1 className="page-title" style={{ marginBottom: 16 }}>
        주식 모의투자
      </h1>

      <div className="auth__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "login"}
          className={`auth__tab${tab === "login" ? " auth__tab--on" : ""}`}
          onClick={() => {
            setTab("login");
            setError(null);
          }}
        >
          로그인
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "signup"}
          className={`auth__tab${tab === "signup" ? " auth__tab--on" : ""}`}
          onClick={() => {
            setTab("signup");
            setError(null);
          }}
        >
          회원가입
        </button>
      </div>

      {tab === "signup" && (
        <p className="auth__notice">
          가입하면 <b>캐릭터 2개(국내·해외)</b>가 만들어지고 <b>각각 1억원</b>이 지급됩니다.
          진짜 돈은 오가지 않는 모의투자예요. 국내 캐릭터는 원화로, 해외 캐릭터는 가입
          시점 환율로 한 번 바꾼 달러로 투자합니다.
        </p>
      )}

      {/* noValidate: 브라우저 기본 경고 말풍선 대신, 우리가 쓴 한국어 안내를
          한 곳(form-error)에서 일관되게 보여준다. */}
      <form onSubmit={submit} noValidate>
        <div className="field">
          <label className="field__label" htmlFor="email">
            이메일
          </label>
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="password">
            비밀번호
          </label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete={tab === "signup" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {tab === "signup" && (
            <span className="field__hint">{MIN_PASSWORD}자 이상으로 정해주세요.</span>
          )}
        </div>

        {tab === "signup" && (
          <div className="field">
            <label className="field__label" htmlFor="nickname">
              별명
            </label>
            <input
              id="nickname"
              className="input"
              type="text"
              autoComplete="nickname"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
            />
          </div>
        )}

        {error && <p className="form-error">{error}</p>}

        <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
          {busy ? "처리 중…" : tab === "signup" ? "가입하고 시작하기" : "로그인"}
        </button>
      </form>
    </div>
  );
}

export default Login;
