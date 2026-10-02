export {
  ENGAGEMENT_STATUSES,
  NO_FILTER,
  engagementTone,
  filterClients,
  isFiltered,
  parseClientFilter,
  summarizeClients,
} from "./model/clients";
export type { CaClient, ClientFilter, ClientSummary, EngagementStatus } from "./model/clients";
export { CaDashboardView } from "./ui/ca-dashboard-view";
export type { CaDashboardViewProps } from "./ui/ca-dashboard-view";
