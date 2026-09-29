import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./card";

describe("Card", () => {
  it("renders every slot", async () => {
    const { container } = render(
      <Card>
        <CardHeader>
          <CardTitle>Example card</CardTitle>
          <CardDescription>Example description</CardDescription>
          <CardAction>
            <Button variant="ghost">Edit</Button>
          </CardAction>
        </CardHeader>
        <CardContent>Body</CardContent>
        <CardFooter>Footer</CardFooter>
      </Card>,
    );
    for (const slot of [
      "card",
      "card-header",
      "card-title",
      "card-description",
      "card-action",
      "card-content",
      "card-footer",
    ]) {
      expect(container.querySelector(`[data-slot="${slot}"]`)).not.toBeNull();
    }
    expect(screen.getByText("Example card").className).toContain("font-semibold");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
