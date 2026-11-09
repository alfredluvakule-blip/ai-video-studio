import type { Metadata } from "next";
import "./globals.css";
import Shell from "@/components/Shell";

export const metadata: Metadata = {
  title: "AI Video Studio",
  description: "Free-first AI video studio: turn an idea, script or photos into a video up to one hour long.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
