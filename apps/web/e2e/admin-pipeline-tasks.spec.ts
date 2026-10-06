import { ADMIN, ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import { pipelineGet } from "./pipeline-helpers";

/**
 * The pipeline's tasks against the pipeline the stack runs. A task opens only from an ingest (a
 * document no parser reads, a document whose text names another type than its source publishes),
 * and the stack runs no ingest, so its queue is empty: the spec compares the page with the
 * pipeline's answer for each status and kind, and the unit tests drive the resolution and the
 * dismissal of a task.
 */
const PAGE = "/admin/pipeline/tasks";

interface TaskRow {
  task_id: string;
}

test.describe("pipeline tasks", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );

    test("lists the open tasks as the pipeline holds them, and the others by status and kind", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await signIn(ANALYST);
      await page.goto("/admin");
      await page
        .locator("aside")
        .getByRole("link", { name: "Pipeline tasks", exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Pipeline tasks" })).toBeVisible();
      const status = page.getByRole("navigation", { name: "Show tasks by status" });
      await expect(status.getByRole("link", { name: "Open" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      const open = await pipelineGet<{ items: TaskRow[] }>(
        "/v1/pipeline/tasks?status=open&limit=25",
      );
      if (open.items.length === 0) {
        await expect(page.getByRole("heading", { name: "No task is open" })).toBeVisible();
      } else {
        await expect(page.locator("article[data-task]")).toHaveCount(open.items.length);
      }
      await expect(page.locator("[data-slot='tasks-read-only']")).toBeVisible();
      await checkA11y();

      await page
        .getByRole("navigation", { name: "Show tasks by kind" })
        .getByRole("link", { name: "Triage" })
        .click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}\\?kind=triage$`));
      await status.getByRole("link", { name: "Every status" }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}\\?status=every&kind=triage$`));
      const triage = await pipelineGet<{ items: TaskRow[] }>(
        "/v1/pipeline/tasks?kind=triage&limit=25",
      );
      if (triage.items.length === 0) {
        await expect(page.getByRole("heading", { name: "No triage task" })).toBeVisible();
      } else {
        await expect(page.locator("article[data-task]")).toHaveCount(triage.items.length);
      }
      await checkA11y();
    });

    test("an admin reads the queue with nothing held back", async ({ page, signIn, checkA11y }) => {
      await signIn(ADMIN);
      await page.goto(`${PAGE}?status=dismissed`);
      await expect(page.locator("[data-slot='tasks-read-only']")).toHaveCount(0);
      const dismissed = await pipelineGet<{ items: TaskRow[] }>(
        "/v1/pipeline/tasks?status=dismissed&limit=25",
      );
      if (dismissed.items.length === 0) {
        await expect(page.getByRole("heading", { name: "No task is dismissed" })).toBeVisible();
      }
      await checkA11y();
    });
  });
});
