"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Meta, api, setToken } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [needsInvite, setNeedsInvite] = useState(false);
  useEffect(() => { api<Meta>("/meta").then((m) => setNeedsInvite(!!m.limits.signup_code_required)).catch(() => {}); }, []);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api<{ token: string }>(`/auth/${mode}`, { body: { email, password, ...(mode === "register" && invite ? { invite_code: invite } : {}) } });
      setToken(r.token);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-screen place-items-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-violet-600 font-bold text-white">▶</span>
          <div>
            <div className="font-semibold text-white">Luvakule AI</div>
            <div className="text-xs text-slate-400">Free to use. No subscription, no card.</div>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="pw">Password</label>
          <input id="pw" className="input" type="password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {mode === "register" && needsInvite && (
          <div>
            <label className="label" htmlFor="invite">Invite code</label>
            <input id="invite" className="input" required value={invite} onChange={(e) => setInvite(e.target.value)} />
          </div>
        )}
        {error && <p className="text-sm text-red-300">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{mode === "login" ? "Sign in" : "Create free account"}</button>
        <button type="button" className="w-full text-center text-sm text-violet-300 hover:underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
