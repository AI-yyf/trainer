import { describeProviderThinking, normalizeProviderThinking, updateProviderThinking } from "../../../../shared/src/providerThinking";

const base = { protocol: "openai_responses", model: "gpt-5", supported: true } as const;

describe("provider thinking", () => {
  it("does not treat a known model catalog entry as thinking evidence", () => {
    const context = { protocol: "openai_responses", model: "listed-model", knownModels: ["listed-model"] } as const;
    expect(describeProviderThinking(context, { reasoningEffort: "high" })).toBeUndefined();
    expect(normalizeProviderThinking({ reasoningEffort: "high" }, context).requestDefaults).toEqual({});
    expect(updateProviderThinking(context, {}, { mode: "enabled", reasoningEffort: "high" })).toEqual({});
  });

  it("describes only explicit or live-confirmed native controls", () => {
    expect(describeProviderThinking(base, { reasoningEffort: "high" })?.kind).toBe("reasoning_effort");
    expect(describeProviderThinking({ protocol: "openai_chat_completions_compatible", model: "unknown" }, {})).toBeUndefined();
    expect(describeProviderThinking({ protocol: "openai_responses", model: "listed-model", knownModels: ["listed-model"], modelCapability: true }, { reasoningEffort: "high" })?.kind).toBe("reasoning_effort");
    expect(describeProviderThinking({ protocol: "openai_responses", model: "live-model", liveEvidence: true }, { reasoningEffort: "high" })?.kind).toBe("reasoning_effort");
  });

  it("does not treat a successful chat probe as thinking evidence", () => {
    const context = { protocol: "openai_chat_completions_compatible", model: "gateway-model" } as const;
    expect(describeProviderThinking(context, { reasoningEffort: "high" })).toBeUndefined();
    expect(updateProviderThinking(context, {}, { mode: "enabled", reasoningEffort: "high" })).toEqual({});
  });

  it("accepts only an observed thinking capability as live evidence", () => {
    const context = {
      protocol: "openai_chat_completions_compatible",
      model: "reasoning-model",
      liveEvidence: true,
    } as const;
    expect(describeProviderThinking(context, { reasoningEffort: "high" })?.kind).toBe("reasoning_effort");
  });

  it("round trips effort and budget fields", () => {
    expect(updateProviderThinking(base, {}, { mode: "enabled", reasoningEffort: "high" })).toEqual({ reasoning: { effort: "high" } });
    expect(updateProviderThinking({ protocol: "anthropic_messages", model: "claude-4", supported: true }, {}, { mode: "enabled", budgetTokens: 4096 })).toEqual({ thinking: { type: "enabled", budget_tokens: 4096 } });
  });

  it("keeps MiniMax thinking disabled until live evidence", () => {
    const result = normalizeProviderThinking({}, { providerName: "MiniMax", model: "MiniMax-M3" });
    expect(result.requestDefaults).toEqual({ extra_body: { thinking: { type: "disabled" } } });
    expect(result.reason).toBe("disabled");
  });

  it("emits MiniMax extra_body.thinking enabled only with live evidence", () => {
    const result = normalizeProviderThinking(
      { thinking: { mode: "enabled" } },
      { providerName: "MiniMax", model: "MiniMax-M2.7", liveEvidence: true },
    );
    expect(result.requestDefaults).toEqual({ extra_body: { thinking: { type: "enabled" } } });
    expect(result.reason).toBe("emitted");
    expect(result.requestDefaults.reasoning_effort).toBeUndefined();
  });
});
