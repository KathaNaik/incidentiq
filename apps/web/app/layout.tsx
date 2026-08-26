import type { Metadata } from "next";

import { DatasetBanner } from "@/components/dataset-banner";
import { NavLink } from "@/components/nav-link";
import "./globals.css";

export const metadata: Metadata = {
  title: "IncidentIQ",
  description:
    "AI-assisted incident investigation for technical operations teams.",
};

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/incidents", label: "Incidents" },
  { href: "/tickets", label: "Tickets" },
  { href: "/evals", label: "Evals" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <DatasetBanner />
        <header className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 px-6 py-3">
            <span className="text-base font-semibold">IncidentIQ</span>
            <nav className="flex gap-1" aria-label="Main">
              {NAV_ITEMS.map((item) => (
                <NavLink key={item.href} href={item.href} label={item.label} />
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
