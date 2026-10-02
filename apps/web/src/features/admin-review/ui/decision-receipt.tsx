"use client";

import { useEffect, useState } from "react";
import { Banner } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";

export interface DecisionReceiptProps {
  tone: "info" | "success" | "warning" | "error";
  title: string;
  detail?: string;
}

const uiTone: Record<string, Tone> = {
  info: "info",
  success: "success",
  warning: "warning",
  error: "danger",
};

export function DecisionReceipt({ tone, title, detail }: DecisionReceiptProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <Banner tone={uiTone[tone] ?? "info"} className="flex flex-col gap-1">
      <p className="font-medium">{title}</p>
      {detail !== undefined && <p className="text-sm opacity-80">{detail}</p>}
    </Banner>
  );
}