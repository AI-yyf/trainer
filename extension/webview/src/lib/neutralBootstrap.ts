import { trainerCommandCatalog } from "../../../../shared/src/commands";
import { createEmptyTrainerStreamingState } from "../../../../shared/src/protocol";

import type { BootstrapData } from "./types";

const EMPTY_CAPABILITIES: BootstrapData["connection"]["provider"]["capabilities"] = {
  chat: false,
  responses: false,
  vision: false,
  embeddings: false,
  tools: false,
  jsonSchema: false,
  structuredOutput: false,
  streaming: false,
};

/**
 * A deliberately content-free baseline for the short interval before the Host
 * has supplied a snapshot. Fixtures stay in the browser preview harness only.
 */
export function createNeutralBootstrapData(
  connectionState: BootstrapData["connection"]["state"] = "offline",
): BootstrapData {
  return {
    workspaceName: "",
    sessionLabel: "",
    connection: {
      state: connectionState,
      provider: {
        name: "",
        model: "",
        capabilities: { ...EMPTY_CAPABILITIES },
      },
    },
    providerConfig: {
      configured: false,
      name: "",
      baseUrl: "",
      model: "",
      apiKeyConfigured: false,
      capabilities: { ...EMPTY_CAPABILITIES },
      availableModels: [],
      modelListStatus: "idle",
    },
    liveContext: {
      diagnosticsSummary: "",
      recentFiles: [],
      recentEditedFiles: [],
      relatedFiles: [],
      diagnosticErrors: 0,
      diagnosticWarnings: 0,
    },
    profile: {
      learnerName: "",
      goals: [],
      weeklyHours: 0,
      preferredStyle: "auto",
      answerPolicy: "auto",
      focusAreas: [],
    },
    plan: {
      id: "",
      title: "",
      frozen: false,
      cadence: "",
      summary: "",
      stages: [],
    },
    task: {
      id: "",
      title: "",
      description: "",
      constraints: [],
      acceptanceCriteria: [],
      nextActionLabel: "",
    },
    evaluation: {
      headline: "",
      summary: "",
      passRate: 0,
      updatedAt: "",
      checks: [],
      nextStep: "",
    },
    memory: {
      currentFocus: "",
      weakSpots: [],
      recentWins: [],
      reviewSummary: "",
      reviewRhythm: "",
      dueReviews: [],
      teachingObservations: [],
      memoryEvidence: [],
      workspace: {},
    },
    workspaceTrainingState: undefined,
    projectIdeas: [],
    projectSources: [],
    reviewQueueSummary: "",
    streamingState: createEmptyTrainerStreamingState(),
    resources: [],
    conversation: [],
    suggestedActions: [],
    commands: trainerCommandCatalog.map((command) => ({ ...command })),
  };
}
