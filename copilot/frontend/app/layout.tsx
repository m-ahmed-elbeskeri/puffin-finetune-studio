import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Oswald } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { RightRail } from "@/components/layout/RightRail";
import { BackendStatus } from "@/components/layout/BackendStatus";
import { Providers } from "@/components/Providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});
// Riso display face — condensed, used in caps for headings and tab labels.
const oswald = Oswald({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Puffin Copilot: fine-tune any open LLM",
  description: "AI-first dashboard and chat for the Puffin LLM fine-tuning platform.",
};

// Runs before first paint so the Blueprint palette lands in the right mode
// with no flash: honour a saved choice, else fall back to the OS preference.
const THEME_INIT = `(function(){try{var t=localStorage.getItem('puffin-theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} ${oswald.variable} font-sans bg-ink-50 text-ink antialiased`}
      >
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            {/* pt-14 clears the fixed mobile top bar; removed from lg up. */}
            <div className="flex-1 min-w-0 flex flex-col pt-14 lg:pt-0">
              <main className="flex-1 min-h-0">
                {children}
              </main>
            </div>
            <RightRail />
          </div>
          <BackendStatus />
        </Providers>
      </body>
    </html>
  );
}
