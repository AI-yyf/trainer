/**
 * CapabilityMatrix - Visual display of protocol capabilities
 *
 * Shows which features each protocol supports at a glance.
 * Part of Provider v2 enhancement per docs/open-source-fit-and-provider-strategy.md §5
 */

import type { ComposerLanguage, ProviderProtocol } from "../../lib/types";
import { resolveCopy, type CopyKey } from "../../lib/i18n/copy";
import type { CapabilityFlags } from "../../../../../shared/src/models";

interface CapabilityMatrixProps {
  protocol: ProviderProtocol;
  capabilities: CapabilityFlags;
  language?: ComposerLanguage;
  className?: string;
}

const CAPABILITY_COPY_KEYS: Record<string, CopyKey> = {
  chat: "capabilityChat",
  responses: "capabilityResponses",
  tools: "capabilityTools",
  streaming: "capabilityStreaming",
  structuredOutput: "capabilityStructuredOutput",
  vision: "capabilityVision",
  embeddings: "capabilityEmbeddings",
  jsonSchema: "capabilityJsonSchema",
};

const CAPABILITY_LABELS: Record<string, Record<ComposerLanguage, string>> = {
  chat: {
    "zh-CN": "对话",
    "en-US": "Chat",
    "es-ES": "Chat",
    "fr-FR": "Chat",
    "de-DE": "Chat",
    "ja-JP": "チャット",
    "ko-KR": "채팅",
    "pt-BR": "Chat",
  },
  responses: {
    "zh-CN": "Responses API",
    "en-US": "Responses API",
    "es-ES": "Responses API",
    "fr-FR": "Responses API",
    "de-DE": "Responses API",
    "ja-JP": "Responses API",
    "ko-KR": "Responses API",
    "pt-BR": "Responses API",
  },
  tools: {
    "zh-CN": "工具调用",
    "en-US": "Tool Calls",
    "es-ES": "Herramientas",
    "fr-FR": "Outils",
    "de-DE": "Werkzeuge",
    "ja-JP": "ツール呼び出し",
    "ko-KR": "도구 호출",
    "pt-BR": "Ferramentas",
  },
  streaming: {
    "zh-CN": "流式输出",
    "en-US": "Streaming",
    "es-ES": "Streaming",
    "fr-FR": "Streaming",
    "de-DE": "Streaming",
    "ja-JP": "ストリーミング",
    "ko-KR": "스트리밍",
    "pt-BR": "Streaming",
  },
  structuredOutput: {
    "zh-CN": "结构化输出",
    "en-US": "Structured Output",
    "es-ES": "Salida Estructurada",
    "fr-FR": "Sortie Structurée",
    "de-DE": "Strukturierte Ausgabe",
    "ja-JP": "構造化出力",
    "ko-KR": "구조화된 출력",
    "pt-BR": "Saída Estruturada",
  },
  vision: {
    "zh-CN": "视觉理解",
    "en-US": "Vision",
    "es-ES": "Visión",
    "fr-FR": "Vision",
    "de-DE": "Vision",
    "ja-JP": "ビジョン",
    "ko-KR": "비전",
    "pt-BR": "Visão",
  },
  embeddings: {
    "zh-CN": "向量嵌入",
    "en-US": "Embeddings",
    "es-ES": "Embeddings",
    "fr-FR": "Embeddings",
    "de-DE": "Embeddings",
    "ja-JP": "エンベディング",
    "ko-KR": "임베딩",
    "pt-BR": "Embeddings",
  },
  jsonSchema: {
    "zh-CN": "JSON Schema",
    "en-US": "JSON Schema",
    "es-ES": "JSON Schema",
    "fr-FR": "JSON Schema",
    "de-DE": "JSON Schema",
    "ja-JP": "JSON Schema",
    "ko-KR": "JSON Schema",
    "pt-BR": "JSON Schema",
  },
};

const PROTOCOL_LABELS: Record<ProviderProtocol, Record<ComposerLanguage, string>> = {
  openai_responses: {
    "zh-CN": "OpenAI Responses",
    "en-US": "OpenAI Responses",
    "es-ES": "OpenAI Responses",
    "fr-FR": "OpenAI Responses",
    "de-DE": "OpenAI Responses",
    "ja-JP": "OpenAI Responses",
    "ko-KR": "OpenAI Responses",
    "pt-BR": "OpenAI Responses",
  },
  openai_chat_completions: {
    "zh-CN": "OpenAI Chat",
    "en-US": "OpenAI Chat",
    "es-ES": "OpenAI Chat",
    "fr-FR": "OpenAI Chat",
    "de-DE": "OpenAI Chat",
    "ja-JP": "OpenAI Chat",
    "ko-KR": "OpenAI Chat",
    "pt-BR": "OpenAI Chat",
  },
  anthropic_messages: {
    "zh-CN": "Anthropic Messages",
    "en-US": "Anthropic Messages",
    "es-ES": "Anthropic Messages",
    "fr-FR": "Anthropic Messages",
    "de-DE": "Anthropic Messages",
    "ja-JP": "Anthropic Messages",
    "ko-KR": "Anthropic Messages",
    "pt-BR": "Anthropic Messages",
  },
  openai_chat_completions_compatible: {
    "zh-CN": "OpenAI 兼容",
    "en-US": "OpenAI Compatible",
    "es-ES": "Compatible OpenAI",
    "fr-FR": "Compatible OpenAI",
    "de-DE": "OpenAI Kompatibel",
    "ja-JP": "OpenAI互換",
    "ko-KR": "OpenAI 호환",
    "pt-BR": "OpenAI Compatível",
  },
  gemini_generate_content: {
    "zh-CN": "Gemini Generate",
    "en-US": "Gemini Generate",
    "es-ES": "Gemini Generate",
    "fr-FR": "Gemini Generate",
    "de-DE": "Gemini Generate",
    "ja-JP": "Gemini Generate",
    "ko-KR": "Gemini Generate",
    "pt-BR": "Gemini Generate",
  },
};

const CAPABILITY_KEYS = [
  "chat",
  "responses",
  "tools",
  "streaming",
  "structuredOutput",
  "vision",
  "embeddings",
  "jsonSchema",
] as const;

function getCapabilityValue(capabilities: CapabilityFlags, key: string): boolean {
  const value = capabilities[key as keyof CapabilityFlags];
  return value ?? false;
}

function getProtocolBadgeClass(protocol: ProviderProtocol): string {
  const classes = ["protocol-badge"];
  if (protocol === "anthropic_messages") {
    classes.push("protocol-badge--anthropic");
  } else if (protocol === "gemini_generate_content") {
    classes.push("protocol-badge--gemini");
  } else if (protocol === "openai_chat_completions_compatible") {
    classes.push("protocol-badge--compatible");
  } else {
    classes.push("protocol-badge--openai");
  }
  return classes.join(" ");
}

function CapabilityIndicator({ enabled, language }: { enabled: boolean; language: ComposerLanguage }) {
  const copy = resolveCopy(language);
  return (
    <span
      className={`capability-matrix__indicator ${enabled ? "capability-matrix__indicator--yes" : "capability-matrix__indicator--no"}`}
      aria-label={enabled ? copy.capabilitySupported : copy.capabilityNotSupported}
    >
      {enabled ? "✓" : "—"}
    </span>
  );
}

export function CapabilityMatrix({
  protocol,
  capabilities,
  language = "en-US",
  className,
}: CapabilityMatrixProps) {
  const copy = resolveCopy(language);
  const capabilityLabel = (key: string) =>
    CAPABILITY_COPY_KEYS[key] ? copy[CAPABILITY_COPY_KEYS[key]] : CAPABILITY_LABELS[key]?.[language] ?? key;

  const protocolLabel = PROTOCOL_LABELS[protocol]?.[language] ?? protocol;

  return (
    <div className={`capability-matrix ${className ?? ""}`}>
      {/* Header row */}
      <div className="capability-matrix__header">
        <div className="capability-matrix__header-cell">
          <span className={getProtocolBadgeClass(protocol)}>{protocolLabel}</span>
        </div>
      </div>

      {/* Capability rows */}
      {CAPABILITY_KEYS.map((key) => (
        <div key={key} className="capability-matrix__row">
          <div className="capability-matrix__cell">
            {capabilityLabel(key)}
          </div>
          <div className="capability-matrix__cell">
            <CapabilityIndicator enabled={getCapabilityValue(capabilities, key)} language={language} />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Compact capability summary for inline display
 */
interface CapabilitySummaryProps {
  capabilities: CapabilityFlags;
  language?: ComposerLanguage;
}

export function CapabilitySummary({
  capabilities,
  language = "en-US",
}: CapabilitySummaryProps) {
  const copy = resolveCopy(language);
  const features: string[] = [];

  if (capabilities.structuredOutput) features.push(copy.capabilityStructuredOutput);
  if (capabilities.tools) features.push(copy.capabilityTools);
  if (capabilities.vision) features.push(copy.capabilityVision);
  if (capabilities.streaming) features.push(copy.capabilityStreaming);
  if (capabilities.embeddings) features.push(copy.capabilityEmbeddings);

  if (features.length === 0) {
    return null;
  }

  return (
    <span className="capability-summary">
      {features.map((feature, i) => (
        <span key={feature} className="capability-summary__item">
          {i > 0 && <span className="capability-summary__sep">·</span>}
          {feature}
        </span>
      ))}
    </span>
  );
}