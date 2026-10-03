import { Card, Skeleton } from "@compliancewatch/ui";

export default function ObligationDetailLoading() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <Skeleton className="h-8 w-72" />
      <Skeleton className="h-4 w-96" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
      <Card className="p-6">
        <Skeleton className="h-32 w-full" />
      </Card>
    </div>
  );
}
