import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LegalDocument } from "@/features/legal";
import { readLegalDocument } from "@/server/legal";
import { LEGAL_DOC_NAMES, isLegalDoc } from "@/shared/config/legal-docs";

interface Params {
  doc: string;
}

// The drafts are read from docs/legal at build time; only the listed names exist.
export const dynamicParams = false;

export function generateStaticParams(): Params[] {
  return LEGAL_DOC_NAMES.map((doc) => ({ doc }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { doc } = await params;
  if (!isLegalDoc(doc)) return {};
  return { title: readLegalDocument(doc).title };
}

export default async function LegalPage({ params }: { params: Promise<Params> }) {
  const { doc } = await params;
  if (!isLegalDoc(doc)) notFound();
  const document = readLegalDocument(doc);
  return (
    <LegalDocument
      title={document.title}
      version={document.version}
      isDraft={document.isDraft}
      html={document.html}
    />
  );
}
