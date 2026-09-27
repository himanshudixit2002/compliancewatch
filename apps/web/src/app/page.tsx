import Link from "next/link";
import { Badge } from "@compliancewatch/ui";

export default function HomePage() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-8">
      <Badge tone="warning">Preview</Badge>
      <h1 className="text-3xl font-semibold">ComplianceWatch</h1>
      <p>
        Owner portal and CA dashboard. Watches regulators for rule changes, decides which apply to
        one specific business, and turns each into a dated obligation.
      </p>
      <Link href="/admin" className="underline">
        Internal tools (/admin)
      </Link>
    </main>
  );
}
