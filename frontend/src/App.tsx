// 세션 확인 → 로그인 또는 업무 화면. 로그아웃·세션 만료 때는 화면에 남은 대화·인용 캐시를 모두 지운다(T-21).
import { useEffect, useState } from "react";
import { ApiError, api, setCsrf } from "./api";
import type { SessionInfo } from "./types";
import { Workspace } from "./Workspace";

export function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checked, setChecked] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // 계정이 바뀌면 이전 계정의 화면 상태를 재사용하지 않도록 업무 화면을 새로 만든다.
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    api
      .session()
      .then(({ data }) => {
        setCsrf(data.csrf_token);
        setSession(data);
      })
      .catch(() => setSession(null))
      .finally(() => setChecked(true));
  }, []);

  function clear(message: string | null) {
    setCsrf(null);
    setSession(null);
    setEpoch((e) => e + 1);
    setNotice(message);
  }

  if (!checked) return <p className="loading">불러오는 중이에요</p>;
  if (!session) {
    return (
      <Login
        notice={notice}
        onLogin={(info) => {
          setCsrf(info.csrf_token);
          setNotice(null);
          setSession(info);
        }}
      />
    );
  }
  return (
    <Workspace
      key={`${session.user_id}-${epoch}`}
      session={session}
      onLogout={() => clear(null)}
      onExpired={() => clear("로그인이 만료됐어요. 다시 로그인해 주세요.")}
    />
  );
}

function Login({ notice, onLogin }: { notice: string | null; onLogin: (info: SessionInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onLogin((await api.login(username, password)).data);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "아이디 또는 비밀번호가 맞지 않아요." : "로그인하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="login-card">
      <h1>사내 업무 도우미</h1>
      <p className="login-lead">교육 일정, 회사 규정, IT 지원을 한곳에서 확인하세요.</p>
      {notice && <p className="notice" role="status">{notice}</p>}
      <form onSubmit={submit} aria-label="로그인">
        <label>
          아이디
          <input name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          비밀번호
          <input name="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="notice" role="alert">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}>로그인</button>
      </form>
      </div>
    </main>
  );
}
