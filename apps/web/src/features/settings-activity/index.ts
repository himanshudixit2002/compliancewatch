/**
 * The activity log feature: the model for the audit trail entries and the view component.
 */
export { ActivityView } from "./ui/activity-view";
export type { ActivityViewProps } from "./ui/activity-view";
export { emptyActivity } from "./model/activity";
export type { ActivityEntry, ActivityView as ActivityViewModel } from "./model/activity";
