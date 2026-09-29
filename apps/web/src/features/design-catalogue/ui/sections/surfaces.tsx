import { useState } from "react";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  ReasonDialog,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function SurfacesSection() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reasonOpen, setReasonOpen] = useState(false);
  return (
    <CatalogueSection id="surfaces" title="Cards, tabs, dialogs and sheets">
      <Example label="Card">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Example card</CardTitle>
            <CardDescription>{FIXTURES.text}</CardDescription>
          </CardHeader>
          <CardContent>{FIXTURES.paragraph}</CardContent>
          <CardFooter>
            <Button size="sm" variant="secondary">
              Example
            </Button>
          </CardFooter>
        </Card>
      </Example>
      <Example label="Tabs">
        <Tabs defaultValue="one" className="w-full max-w-md">
          <TabsList>
            <TabsTrigger value="one">Example one</TabsTrigger>
            <TabsTrigger value="two">Example two</TabsTrigger>
          </TabsList>
          <TabsContent value="one">First panel: {FIXTURES.text}</TabsContent>
          <TabsContent value="two">Second panel: {FIXTURES.paragraph}</TabsContent>
        </Tabs>
      </Example>
      <Example label="Dialog">
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="secondary">Open dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Example dialog</DialogTitle>
              <DialogDescription>{FIXTURES.text}</DialogDescription>
            </DialogHeader>
            <p className="text-sm text-fg">{FIXTURES.paragraph}</p>
            <DialogFooter showCloseButton />
          </DialogContent>
        </Dialog>
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          trigger={<Button variant="danger">Open confirm dialog</Button>}
          title="Delete the example?"
          description="Records nothing; this is the catalogue."
          confirmLabel="Delete"
          destructive
          onConfirm={() => {
            toast("Example confirmed");
            setConfirmOpen(false);
          }}
        />
        <ReasonDialog
          open={reasonOpen}
          onOpenChange={setReasonOpen}
          trigger={<Button variant="secondary">Open reason dialog</Button>}
          title="Reject the example"
          description="The reason is kept with the decision."
          confirmLabel="Reject"
          onConfirm={(reason) => {
            toast(`Example reason: ${reason.length} characters`);
            setReasonOpen(false);
          }}
        />
      </Example>
      <Example label="Sheet">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="secondary">Open sheet</Button>
          </SheetTrigger>
          <SheetContent side="right">
            <SheetHeader>
              <SheetTitle>Example sheet</SheetTitle>
              <SheetDescription>{FIXTURES.text}</SheetDescription>
            </SheetHeader>
            <p className="p-4 text-sm text-fg">{FIXTURES.paragraph}</p>
          </SheetContent>
        </Sheet>
      </Example>
    </CatalogueSection>
  );
}
