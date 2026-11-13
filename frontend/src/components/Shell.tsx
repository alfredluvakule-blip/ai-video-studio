"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard", icon: "◧" },
  { href: "/create", label: "Create Video", icon: "＋" },
  { href: "/text-to-video", label: "Text to Video", icon: "✎" },
  { href: "/image-to-video", label: "Image to Video", icon: "▣" },
  { href: "/script-to-video", label: "Script to Video", icon: "☰" },
  { href: "/storyboard", label: "Storyboard Generator", icon: "▤" },
  { href: "/editor", label: "Video Editor", icon: "✂" },
  { href: "/projects", label: "My Projects", icon: "▦" },
  { href: "/media", label: "Media Library", icon: "◉" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const isAuthPage = path === "/login";

  useEffect(() => {
    if (isAuthPage) return;
    if (!getToken()) { router.replace("/login"); return; }
    api<{ email: string }>("/auth/me").then((u) => setEmail(u.email)).catch(() => {});
  }, [isAuthPage, router]);

  useEffect(() => setOpen(false), [path]);

  if (isAuthPage) return <>{children}</>;

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <div className="flex min-h-screen">
      <aside className={`fixed inset-y-0 left-0 z-30 w-64 shrink-0 border-r border-white/10 bg-[#0e1018] p-4 transition-transform lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <Link href="/" className="mb-6 flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-violet-600 font-bold text-white">▶</span>
          <span className="font-semibold text-white">Luvakule AI</span>
        </Link>
        <nav className="space-y-1">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href}
              className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${active(n.href) ? "bg-violet-600/20 text-violet-200" : "text-slate-300 hover:bg-white/5"}`}>
              <span className="w-4 text-center opacity-80">{n.icon}</span>{n.label}
            </Link>
          ))}
        </nav>
        <div className="absolute bottom-4 left-4 right-4 space-y-2 text-xs text-slate-500">
          <div className="truncate">{email}</div>
          <button className="btn-ghost w-full" onClick={async () => { await api("/auth/logout", { method: "POST" }).catch(() => {}); setToken(null); router.replace("/login"); }}>
            Sign out
          </button>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-white/10 bg-[#0b0d14]/90 px-4 py-3 backdrop-blur lg:hidden">
          <button className="btn-ghost px-3" onClick={() => setOpen(true)} aria-label="Open menu">☰</button>
          <span className="font-semibold">Luvakule AI</span>
        </header>
        <main className="mx-auto max-w-7xl p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
