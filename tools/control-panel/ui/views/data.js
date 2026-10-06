// Data: fill the databases with demo data, keep them up to date, back up, restore and reset.

import { actionButton } from "../actions.js";
import { add, h } from "../dom.js";
import * as store from "../store.js";
import { rich } from "../ui.js";
import { actionSections, place, revealSection } from "./common.js";

export const title = "Data";

const SECTIONS = [
  {
    id: "demo-data",
    title: "Demo data",
    lead: () =>
      rich(
        "Made-up businesses and rules to look at. Everything they hold is {synthetic}, and none of it leaves this Mac.",
      ),
    actions: ["load-demo-data", "product-seed", "demo"],
  },
  {
    id: "update",
    title: "Keep the databases up to date",
    lead: () =>
      rich(
        "A {migration} updates a database's structure to match the code. The checks here only read.",
      ),
    actions: ["migrate", "seed-check", "migrations-check", "migrations-catalog", "data-quality"],
  },
  {
    id: "backups",
    title: "Back up, restore and reset",
    lead: () =>
      rich(
        "A {backup} is a copy of the database in a file in var/backups. Restore and Reset replace what is there now, so they ask first and offer a backup.",
      ),
    actions: ["backup", "restore", "reset"],
    headerActions: (scope) =>
      store.action("open-backups-folder")
        ? [
            scope.use(
              actionButton("open-backups-folder", {
                label: "Open the backups folder",
                iconName: "folder",
                size: "sm",
              }),
            ),
          ]
        : [],
  },
  {
    id: "inside",
    title: "Look inside",
    lead: "For people who know SQL: a database prompt in Terminal.",
    actions: ["psql"],
  },
];

place("data", SECTIONS.flatMap((s) => s.actions).concat(["open-backups-folder"]));

export function render(root, { scope, params }) {
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Data", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "Your local databases: fill them with demo data, update them, back them up, restore or reset them. The data lives in Docker on this Mac and stays when you stop.",
        ),
      ),
    ),
  );
  actionSections(root, scope, "data", SECTIONS);
  revealSection(root, params[0]);
  return { update: (next) => revealSection(root, next[0]) };
}
