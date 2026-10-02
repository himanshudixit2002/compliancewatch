import type { Route } from "next";

export interface DashboardView {
  complianceScore: number;
  overdueObligations: number;
  dueThisWeek: number;
  completedObligations: number;
  businesses: Business[];
  recentActivities: Activity[];
  urgentActions: UrgentAction[];
  filter: string;
  sort: string;
}

export interface Business {
  id: string;
  name: string;
  type: string;
  complianceScore: number;
  status: string;
  lastUpdated: string;
}

export interface Activity {
  id: string;
  description: string;
  icon?: string;
  timestamp: string;
  type: string;
}

export interface UrgentAction {
  id: string;
  title: string;
  description: string;
  dueLabel: string;
  href: string | Route;
}

export function emptyDashboard(): DashboardView {
  return {
    complianceScore: 0,
    overdueObligations: 0,
    dueThisWeek: 0,
    completedObligations: 0,
    businesses: [],
    recentActivities: [],
    urgentActions: [],
    filter: "all",
    sort: "updated",
  };
}
