import type { CitationPart, TrainerMessagePart } from "./protocol";

const PREPARATION_REQUESTS = [
  /(?:请(?:帮我)?|帮我|协助我)(?:完成|做好|做一次)?备课/u,
  /(?:请|帮我|请帮我)?(?:为|围绕)[^。！？\n]{1,90}(?:备课|准备(?:完整)?教学材料)/u,
  /\b(?:prepare|draft|create|help me (?:prepare|plan)) (?:a |the |my )?(?:lesson|teaching materials|research brief|lesson prep)\b/iu,
  /\bprepara(?:r)? (?:una |la )?(?:clase|lección|material didáctico)\b/iu,
  /\bprépare(?:r|z)? (?:un |le |une |la )?(?:cours|leçon|support pédagogique)\b/iu,
  /\b(?:erstelle|bereite)\b[^.!?\n]{0,65}\b(?:unterricht|lehrmaterial)\b/iu,
  /(?:授業|教材)を準備(?:して|してください)/u,
  /(?:수업|교재)(?:을|를)?\s*준비해/u,
  /\b(?:prepare|preparar) (?:uma |a )?(?:aula|material didático)\b/iu,
];
const PREPARATION_NEGATION = /(?:不要|不用|无需|别|如何|怎么)(?:帮我|完成)?备课|\b(?:don't|do not|how (?:do i|to)) (?:prepare|draft|create)\b/iu;

export function preparationRequested(message: string): boolean {
  const text = message.split(/\r?\n/u).filter((line) => !/^\s*>/u.test(line)).join("\n")
    .replace(/[「『“"][^\n]*?[」』”"]|`[^`\n]+`/gu, "");
  return !PREPARATION_NEGATION.test(text) && PREPARATION_REQUESTS.some((pattern) => pattern.test(text));
}

export type ResearchPreparation =
  | { status: "saved"; assetId: string; title: string }
  | { status: "needs_sources" | "needs_context" | "unavailable" };

export function mapResearchPreparation(value: unknown): ResearchPreparation | undefined {
  const item = record(value);
  if (item?.status === "saved") {
    const assetId = string(item.asset_id);
    const title = string(item.title);
    if (assetId && title) return { status: "saved", assetId, title };
  }
  if (item?.status === "needs_sources" || item?.status === "needs_context" || item?.status === "unavailable") {
    return { status: item.status };
  }
  return undefined;
}

export const RESEARCH_BRIEF_SECTIONS = [
  "keyQuestions", "sourceDisagreements", "concepts", "prerequisites", "knowledgeStructure",
  "teachingOrder", "explanationStrategy", "examples", "misconceptions", "checkQuestions",
  "acceptanceCriteria", "openQuestions", "followUpResearch",
] as const;

type BriefSection = (typeof RESEARCH_BRIEF_SECTIONS)[number];

export interface ResearchCitationPin {
  versionId: string;
  contentHash: string;
  excerpt: string;
  lineEnd: number;
}

export function resolveResearchCitationLine(
  document: string, bodyLine: number, pin: Pick<ResearchCitationPin, "excerpt" | "lineEnd">,
  hasCanonicalFrontMatter: boolean,
): number | undefined {
  const source = document.replace(/\r\n/g, "\n");
  const frontMatter = hasCanonicalFrontMatter ? /^---\n[\s\S]*?\n---\n+/.exec(source)?.[0] : undefined;
  const offset = frontMatter ? frontMatter.split("\n").length - 1 : 0;
  const lines = source.split("\n");
  const start = offset + bodyLine;
  const end = offset + pin.lineEnd;
  if (!Number.isInteger(bodyLine) || !Number.isInteger(pin.lineEnd) || bodyLine < 1 || end < start ||
    end > lines.length || !pin.excerpt.trim()) return undefined;
  const match = lines.slice(start - 1, end).join("\n").indexOf(pin.excerpt.replace(/\r\n/g, "\n"));
  return match >= 0 && match < lines[start - 1].length ? start : undefined;
}

export interface ResearchBriefView {
  id: string;
  title: string;
  goal: string;
  updatedAt?: string;
  findings: {
    statement: string;
    status: "sourced" | "inferred" | "unverified";
    citations: CitationPart[];
  }[];
  sections: Partial<Record<BriefSection, string[]>>;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function string(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function items(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function mapCitation(value: unknown): CitationPart | undefined {
  const ref = record(value);
  const metadata = record(ref?.metadata);
  const location = record(metadata?.location);
  const resourceId = string(metadata?.resource_id);
  const versionId = string(metadata?.version_id);
  const contentHash = string(metadata?.content_hash);
  const snippet = string(metadata?.excerpt);
  const line = location?.line_start;
  if (ref?.kind !== "resource" || !resourceId || resourceId !== ref.ref || !versionId || !contentHash ||
    !snippet || typeof line !== "number" || !Number.isInteger(line) || line < 1) return undefined;
  const title = string(ref.label) || resourceId;
  return { type: "citation", resourceId, versionId, contentHash, location, snippet, label: title, title,
    referenceOrigin: "research_brief" };
}

export function mapResearchBriefAsset(value: unknown): ResearchBriefView | undefined {
  const asset = record(value);
  if (!asset || (asset.assetType ?? asset.asset_type) !== "research_brief" || asset.status === "deleted") return undefined;
  const body = record(asset.payload);
  const id = string(asset.id);
  const title = string(asset.title);
  if (!id || !title || !body) return undefined;

  const findings: ResearchBriefView["findings"] = [];
  for (const value of items(body.findings)) {
    const finding = record(value);
    const statement = string(finding?.statement);
    if (!statement) continue;
    const refs = items(finding?.sourceRefs ?? finding?.source_refs);
    const citations = refs.map(mapCitation).filter((part): part is CitationPart => Boolean(part));
    const claim = finding?.claimStatus ?? finding?.claim_status;
    const status = claim === "inferred" ? "inferred" :
      claim === "sourced" && citations.length && citations.length === refs.length ? "sourced" : "unverified";
    findings.push({ statement, status, citations });
  }

  const sections: ResearchBriefView["sections"] = {};
  for (const key of RESEARCH_BRIEF_SECTIONS) {
    const value = body[key] ?? body[key.replace(/[A-Z]/g, (character) => `_${character.toLowerCase()}`)];
    if (key === "explanationStrategy") {
      const strategy = string(value);
      if (strategy) sections[key] = [strategy];
      continue;
    }
    const lines = key === "checkQuestions" ? items(value).map((entry) => {
      const check = record(entry);
      return [string(check?.question), ...items(check?.acceptance).map(string)].filter(Boolean).join("\n");
    }) : items(value).map(string);
    if (lines.some(Boolean)) sections[key] = lines.filter(Boolean);
  }

  return { id, title, goal: string(body.researchGoal ?? body.research_goal),
    updatedAt: string(asset.updatedAt ?? asset.updated_at) || undefined, findings, sections };
}

export function mapResearchBriefCatalog(value: unknown): ResearchBriefView[] | undefined {
  const catalog = record(value);
  if (!Array.isArray(catalog?.active)) return undefined;
  return catalog.active.map((entry) => mapResearchBriefAsset(record(entry)?.asset))
    .filter((brief): brief is ResearchBriefView => Boolean(brief))
    .sort((left, right) => (right.updatedAt ?? "").localeCompare(left.updatedAt ?? ""));
}

export function upsertResearchBrief(briefs: ResearchBriefView[] | undefined, brief: ResearchBriefView): ResearchBriefView[] {
  return [brief, ...(briefs ?? []).filter((item) => item.id !== brief.id)];
}

export function researchBriefResourceIds(message: {
  sourceResourceIds?: string[];
  parts?: TrainerMessagePart[];
}): string[] {
  const cited = message.parts?.flatMap((part) => part.type === "citation" && !part.url && !part.stale
    ? [part.resourceId] : []) ?? [];
  return [...new Set([...cited, ...(message.sourceResourceIds ?? [])].filter(Boolean))].slice(0, 4);
}
