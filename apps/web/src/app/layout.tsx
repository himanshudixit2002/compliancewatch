import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Toaster } from "@compliancewatch/ui";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ComplianceWatch", template: "%s | ComplianceWatch" },
  description: "Regulatory change, decided for one specific business.",
};

// suppressHydrationWarning: the colour scheme class on <html> may be set before hydration.
export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-bg font-sans text-fg antialiased">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
