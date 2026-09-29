import type { Business, Onboarding, QuestionState, ReviewTask } from "@/entities/business/types";
import type { Ontology, OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { attributeLabel } from "./attributes";
import { onboardingProgress, type OnboardingProgress } from "./progress";
import {
  attributeForQuestion,
  businessNodes,
  checklistItems,
  nodeLabel,
  pickQuestion,
  skipKey,
} from "./questions";
import { reviewTaskRows, type ReviewTaskRow } from "./review-tasks";

/**
 * The views of the questions step and the onboarding summary, from what the business API and the
 * review-task route returned: the business with its stored values, the checklist, the ontology
 * and the review tasks on the business's nodes.
 */
export interface OnboardingState {
  business: Business;
  onboarding: Onboarding;
  ontology: Ontology;
  /** Every review task on the entity and its registrations. */
  tasks: readonly ReviewTask[];
}

export interface QuestionView {
  nodeId: string;
  key: string;
  /** The year a per-year answer is for; null otherwise. */
  asOfFy: string | null;
  /** The question as the ontology words it, the page's h1. */
  heading: string;
  /** The ontology's help line, or its definition when there is no help line. */
  help: string;
  /** Which node the answer is stored on: the business or one registration. */
  about: string;
  /** The sentence naming the year of a per-year question; null for any other. */
  yearText: string | null;
  /** True when this question was answered "Not sure" before, in an earlier run. */
  wasUnsure: boolean;
  /** Undefined when the question's value type is one the controls cannot draw. */
  attribute: OntologyAttribute | undefined;
  type: string;
}

export interface SavedNotice {
  label: string;
  /** True when the answer opened a review task (an open "does not apply" task for the key). */
  reviewTaskOpened: boolean;
}

export interface QuestionStepView {
  businessId: string;
  businessName: string;
  progress: OnboardingProgress;
  /** Checklist items stored as "Not sure". */
  unsureCount: number;
  /** Null when nothing is left to ask in this run. */
  question: QuestionView | null;
  /** The open review tasks on the business, newest first. */
  reviewTasks: ReviewTaskRow[];
  saved: SavedNotice | null;
}

export interface OpenItem {
  id: string;
  label: string;
  about: string;
}

export interface DoneSummaryView {
  businessId: string;
  businessName: string;
  pan: string;
  gstins: string[];
  progress: OnboardingProgress;
  counts: Record<QuestionState, number>;
  /** Answered "Not sure": asked again when the person chooses to. */
  unsure: OpenItem[];
  /** Never answered, when the person stopped before the end. */
  missing: OpenItem[];
  reviewTasks: ReviewTaskRow[];
}

function openTaskRows(state: OnboardingState): ReviewTaskRow[] {
  return reviewTaskRows(
    state.tasks.filter((task) => task.open),
    businessNodes(state.business),
  );
}

function questionView(state: OnboardingState, skipped: ReadonlySet<string>): QuestionView | null {
  const question = pickQuestion(state.onboarding, state.business, state.ontology, skipped);
  if (question === null) return null;
  const attribute = attributeForQuestion(question, state.ontology);
  const help = question.help.trim() !== "" ? question.help : (attribute?.definition ?? "");
  return {
    nodeId: question.nodeId,
    key: question.key,
    asOfFy: question.asOfFy,
    heading: question.question.trim() !== "" ? question.question : attributeLabel(question.key),
    help,
    about: nodeLabel(state.business, question.nodeId),
    yearText: question.asOfFy === null ? null : t("question.forYear", { fy: question.asOfFy }),
    wasUnsure: question.state === "unsure",
    attribute,
    type: question.type,
  };
}

function savedNotice(state: OnboardingState, saved: string | undefined): SavedNotice | null {
  if (saved === undefined || saved === "") return null;
  return {
    label: attributeLabel(saved),
    reviewTaskOpened: state.tasks.some(
      (task) => task.open && task.attributeKey === saved && task.reason === "not_applicable",
    ),
  };
}

export function questionStepView(
  state: OnboardingState,
  skipped: ReadonlySet<string>,
  saved?: string,
): QuestionStepView {
  const items = checklistItems(state.business, state.ontology, state.onboarding.asOfFy);
  return {
    businessId: state.business.id,
    businessName: state.business.name,
    progress: onboardingProgress(state.onboarding),
    unsureCount: items.filter((item) => item.state === "unsure").length,
    question: questionView(state, skipped),
    reviewTasks: openTaskRows(state),
    saved: savedNotice(state, saved),
  };
}

export function doneSummaryView(state: OnboardingState): DoneSummaryView {
  const items = checklistItems(state.business, state.ontology, state.onboarding.asOfFy);
  const counts: Record<QuestionState, number> = {
    missing: 0,
    unsure: 0,
    known: 0,
    not_applicable: 0,
  };
  for (const item of items) counts[item.state] += 1;
  const open = (wanted: QuestionState): OpenItem[] =>
    items
      .filter((item) => item.state === wanted)
      .map((item) => ({
        id: skipKey(item.nodeId, item.key),
        label: attributeLabel(item.key),
        about: nodeLabel(state.business, item.nodeId),
      }));
  return {
    businessId: state.business.id,
    businessName: state.business.name,
    pan: state.business.pan,
    gstins: state.business.registrations.map((node) => node.key),
    progress: onboardingProgress(state.onboarding),
    counts,
    unsure: open("unsure"),
    missing: open("missing"),
    reviewTasks: openTaskRows(state),
  };
}
