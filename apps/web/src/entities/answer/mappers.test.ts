import { describe, expect, it } from "vitest";
import { answerDto, notCoveredDto } from "@/test/answer-fixture";
import { REGISTRATION_ID } from "@/test/obligation-fixture";
import { answerFromDto, questionToDto } from "./mappers";

describe("answer mappers", () => {
  it("map an answer with its layer and citations", () => {
    const answer = answerFromDto(answerDto());
    expect(answer).toMatchObject({
      outcome: "answered",
      text: "Example answer: due on 20 Jan 2000.",
      layer: "structured",
      reason: null,
      asOf: "2000-01-10",
    });
    expect(answer.citations[0]).toMatchObject({ clauseRef: "en.p2" });
    expect(answer.layers).toEqual([{ layer: "structured", result: "answered", reason: null }]);
  });

  it("map a question that is not covered with every layer that ran", () => {
    const answer = answerFromDto(notCoveredDto());
    expect(answer.outcome).toBe("not_covered");
    expect(answer.reason).toBe("no_evidence");
    expect(answer.layers.map((run) => run.result)).toEqual(["passed", "not_covered"]);
  });

  it("send the question trimmed with the node it is about", () => {
    expect(questionToDto({ text: "  Example question?  ", nodeId: REGISTRATION_ID })).toEqual({
      question: "Example question?",
      business_node_id: REGISTRATION_ID,
    });
  });
});
