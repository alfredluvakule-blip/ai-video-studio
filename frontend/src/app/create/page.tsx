import Link from "next/link";

const OPTIONS = [
  { href: "/text-to-video", title: "Text to Video", text: "Start from an idea or prompt. Choose length up to 60 minutes.", icon: "✎" },
  { href: "/image-to-video", title: "Image to Video", text: "Animate your photos with camera motion, narration and music.", icon: "▣" },
  { href: "/script-to-video", title: "Script to Video", text: "Paste a script. It becomes scenes, voice-over and subtitles.", icon: "☰" },
];

const USES = ["Children's educational videos", "Cartoon storytelling", "Medical & healthcare education", "Documentaries",
  "YouTube long-form", "TikTok & Instagram Reels", "Training & instructional videos", "Animated presentations",
  "Music videos (with your own licensed track)"];

export default function Create() {
  return (
    <div className="space-y-8">
      <div><h1 className="h1">Create Video</h1><p className="muted">Pick how you want to start.</p></div>
      <div className="grid gap-4 md:grid-cols-3">
        {OPTIONS.map((o) => (
          <Link key={o.href} href={o.href} className="card space-y-3 hover:border-violet-500/50">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-violet-600/20 text-xl text-violet-200">{o.icon}</span>
            <div className="text-lg font-semibold text-white">{o.title}</div>
            <p className="muted">{o.text}</p>
          </Link>
        ))}
      </div>
      <div className="card">
        <div className="label mb-3">Made for</div>
        <div className="flex flex-wrap gap-2">{USES.map((u) => <span key={u} className="badge bg-white/5 text-slate-300">{u}</span>)}</div>
      </div>
    </div>
  );
}
