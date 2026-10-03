/**
 * The data rights feature: the model for data subject access and rectification requests and
 * the view component.
 */
export { DataRightsView } from "./ui/data-rights-view";
export type { DataRightsViewProps } from "./ui/data-rights-view";
export { emptyDataRights } from "./model/data-rights";
export type { DataRight, DataRightStatus, DataRightType, DataRightsView as DataRightsViewModel } from "./model/data-rights";
