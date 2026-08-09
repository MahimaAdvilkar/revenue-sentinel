import type { Metadata } from "next";
import { Nav, } from "@/components/Primitives";
import { SimulatedBanner } from "@/components/Simulated";
import "./globals.css";

export const metadata: Metadata = {
  title: "Revenue Sentinel",
  description: "Agentic AI GTM Control Tower — SIMULATED environment",
};

/**
 * The banner is in the root layout deliberately: it is not dismissible and cannot be
 * scrolled away from on one screen and forgotten on another (rule 5).
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SimulatedBanner />
        <header className="header">
          <span className="brand">Revenue Sentinel</span>
          <Nav />
        </header>
        <main>{children}</main>
        <footer className="footer">
          Offline by construction — this page loads no external fonts, scripts, or assets
          and talks only to the local API.
        </footer>
      </body>
    </html>
  );
}
