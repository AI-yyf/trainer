import { COMMAND_IDS } from './constants';
import type { TrainerWebviewMessage } from './types';

export interface ResolvedWebviewCommand {
  commandId: string;
  payload?: unknown;
}

/**
 * One routing table for every workbench webview surface (sidebar view and the
 * open-in-editor panel). Both surfaces run the same bundle, so a message that
 * resolves to a host command must resolve identically wherever it was posted.
 * Lifecycle messages (`webview/ready`, `state/ack`, `request/bootstrap`, ...)
 * return undefined: each surface owns its own lifecycle bookkeeping.
 */
export function resolveWebviewCommand(
  message: TrainerWebviewMessage,
): ResolvedWebviewCommand | undefined {
  switch (message.type) {
    case 'command/execute':
      return {
        commandId: message.payload.commandId,
        payload: message.payload.payload,
      };
    case 'settings/primeProviderModels':
      return { commandId: COMMAND_IDS.primeProviderModels };
    case 'session/sendMessage':
      return { commandId: COMMAND_IDS.sendMessage, payload: message.payload };
    case 'session/sendStreamMessage':
      return { commandId: COMMAND_IDS.sendStreamMessage, payload: message.payload };
    case 'session/cancelStreamMessage':
      return { commandId: COMMAND_IDS.cancelStreamMessage, payload: message.payload };
    case 'settings/saveCoach':
      return { commandId: COMMAND_IDS.saveCoachSettings, payload: message.payload };
    case 'plan/generate':
      return { commandId: COMMAND_IDS.generatePlan };
    case 'plan/freeze':
      return {
        commandId: COMMAND_IDS.updatePlan,
        payload: { frozen: message.payload.frozen },
      };
    case 'task/specify':
      return {
        commandId: COMMAND_IDS.taskSpecify,
        payload: message.payload,
      };
    case 'task/next':
      return { commandId: COMMAND_IDS.nextTask };
    case 'task/evaluateCurrentFile':
      return {
        commandId: COMMAND_IDS.evaluateCurrentFile,
        payload: message.payload,
      };
    case 'resource/upload':
      return { commandId: COMMAND_IDS.uploadResource, payload: message.payload };
    case 'resource/open':
      return {
        commandId: COMMAND_IDS.openResource,
        payload: message.payload,
      };
    case 'ui/liveFollow':
    case 'ui/focus':
    case 'ui/collapseToSidebar':
      return undefined;
    default:
      return resolveResearchCompatibilityCommand(message);
  }
}

function resolveResearchCompatibilityCommand(
  message: TrainerWebviewMessage,
): ResolvedWebviewCommand | undefined {
  switch (message.type) {
    case 'research/create':
      return { commandId: COMMAND_IDS.createResearch, payload: message.payload };
    case 'research/addTheme':
      return { commandId: COMMAND_IDS.addResearchTheme, payload: message.payload };
    case 'research/activateTheme':
      return { commandId: COMMAND_IDS.activateResearchTheme, payload: message.payload };
    case 'research/advance':
      return { commandId: COMMAND_IDS.advanceResearch, payload: message.payload };
    case 'research/message':
      return { commandId: COMMAND_IDS.researchMessage, payload: message.payload };
    case 'research/streamMessage':
      return { commandId: COMMAND_IDS.researchStreamMessage, payload: message.payload };
    case 'research/approve':
      return { commandId: COMMAND_IDS.approveResearchDecision, payload: message.payload };
    case 'research/getStatus':
      return { commandId: COMMAND_IDS.getResearchStatus, payload: message.payload };
    default:
      return undefined;
  }
}
