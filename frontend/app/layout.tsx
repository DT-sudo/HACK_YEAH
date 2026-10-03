import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "@/lib/app-context";
import { TopBar } from "@/components/TopBar";

export const metadata: Metadata = {
  title: "VitalContext",
  description: "AI-assisted pre-visit intake and chart context for clinics. Synthetic demo data only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:ital,wght@0,400;0,500;0,700;1,400&family=Atkinson+Hyperlegible+Mono:wght@400;500&display=swap" />
      </head>
      <body>
        <AppProvider>
          <TopBar />
          <main className="page">{children}</main>
        </AppProvider>
      </body>
    </html>
  );
}
