import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import {
  ANSWER_FIELDS,
  QuestionStep,
  answerQuestion,
  getQuestionStep,
  isAttributeKey,
  readSkipList,
} from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.onboarding.questions");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<{ saved?: string | string[] }>;
}

export default async function OnboardingQuestionsPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const { saved } = await searchParams;
  const savedKey = typeof saved === "string" && isAttributeKey(saved) ? saved : undefined;
  const step = await getQuestionStep(session, businessId, await readSkipList(businessId), savedKey);
  if (!step.ok) {
    if (step.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={step.error} />;
  }
  const doneHref = hrefFor(screenById("owner.onboarding.done"), { businessId });
  if (step.value.question === null) redirect(doneHref);
  return (
    <QuestionStep
      view={step.value}
      action={answerQuestion}
      fields={ANSWER_FIELDS}
      doneHref={doneHref}
    />
  );
}
