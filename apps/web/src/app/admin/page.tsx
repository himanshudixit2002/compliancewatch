export default function AdminHomePage() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-8">
      <h1 className="text-3xl font-semibold">Admin</h1>
      <p>
        Internal tools live under /admin behind role gates (guide section 15): review workbench,
        source manager, pipeline console, eval dashboard, prompt and model registry, ontology
        editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and
        replay, feature flag console. Nothing is wired yet.
      </p>
    </main>
  );
}
