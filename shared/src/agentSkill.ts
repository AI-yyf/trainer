/**
 * Agent Skills open standard — types, parser, and validator (§一-§八).
 *
 * The ONLY external skill format. Trainer-internal extensions live in
 * `metadata.trainer.*` (namespaced, string→string per the standard).
 * Unknown metadata keys are preserved for round-trip compatibility.
 *
 * Standard structure:
 *   <name>/
 *     SKILL.md        (required, YAML frontmatter + markdown body)
 *     references/     (optional, progressive disclosure)
 *     scripts/        (optional, requires explicit user approval)
 *     assets/         (optional)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentSkillFrontmatter {
  /** 1–64 chars, lowercase a-z / 0-9 / hyphen, no leading/trailing/double hyphen. */
  name: string;
  /** 1–1024 chars. Must answer "what does this do?" and "when to use?". */
  description: string;
  license?: string;
  compatibility?: string;
  /** Standard metadata is string→string. Trainer uses `trainer.*` namespace. */
  metadata?: Record<string, string>;
  /** Experimental field; treated as a compatibility hint, NOT a security boundary. */
  allowedTools?: string[];
}

export interface AgentSkill {
  frontmatter: AgentSkillFrontmatter;
  /** Markdown body after frontmatter (the teaching workflow). */
  body: string;
  /** Directory containing SKILL.md (relative or absolute). */
  skillDir: string;
  /** Resolved relative references mentioned in the body. */
  references: string[];
  /** Raw frontmatter YAML text (for round-trip fidelity). */
  rawFrontmatter: string;
  /** Metadata keys not recognised by Trainer — preserved for round-trip. */
  unknownMetadata: Record<string, string>;
}

export interface AgentSkillValidationError {
  field: string;
  message: string;
}

export interface AgentSkillParseResult {
  skill?: AgentSkill;
  errors: AgentSkillValidationError[];
  warnings: AgentSkillValidationError[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SKILL_MD_FILENAME = 'SKILL.md';

export const TRAINER_METADATA_PREFIX = 'trainer.';

export const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export const MAX_NAME_LENGTH = 64;
export const MAX_DESCRIPTION_LENGTH = 1024;

// ---------------------------------------------------------------------------
// Frontmatter YAML parser (minimal — handles key: value and nested metadata)
// ---------------------------------------------------------------------------

export function parseFrontmatterYaml(raw: string): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  let currentKey = '';
  let inMetadata = false;
  let metadataObj: Record<string, string> = {};

  for (const line of raw.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) {
      continue;
    }
    const topMatch = line.match(/^(\w[\w-]*):\s*(.*)/);
    if (topMatch && !line.startsWith(' ')) {
      currentKey = topMatch[1];
      const value = topMatch[2].trim();
      if (currentKey === 'metadata') {
        if (!value) {
          inMetadata = true;
          metadataObj = {};
          result.metadata = metadataObj;
        } else {
          result.metadata = value;
          inMetadata = false;
        }
      } else {
        result[currentKey] = value;
        inMetadata = false;
      }
      continue;
    }
    // Nested key (metadata sub-keys)
    const nestedMatch = line.match(/^  (\S[^:]*):\s*(.*)/);
    if (nestedMatch && inMetadata) {
      metadataObj[nestedMatch[1].trim()] = nestedMatch[2].trim().replace(/^["']|["']$/g, '');
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

export function validateFrontmatter(fm: AgentSkillFrontmatter): AgentSkillValidationError[] {
  const errors: AgentSkillValidationError[] = [];

  if (!fm.name) {
    errors.push({ field: 'name', message: 'name is required.' });
  } else {
    if (fm.name.length > MAX_NAME_LENGTH) {
      errors.push({ field: 'name', message: `name exceeds ${MAX_NAME_LENGTH} characters.` });
    }
    if (!NAME_PATTERN.test(fm.name)) {
      errors.push({
        field: 'name',
        message: 'name must be lowercase a-z, 0-9, hyphens only. No leading/trailing/double hyphens.',
      });
    }
  }

  if (!fm.description) {
    errors.push({ field: 'description', message: 'description is required.' });
  } else if (fm.description.length > MAX_DESCRIPTION_LENGTH) {
    errors.push({ field: 'description', message: `description exceeds ${MAX_DESCRIPTION_LENGTH} characters.` });
  }

  return errors;
}

export function validateMetadata(metadata: Record<string, string>): AgentSkillValidationError[] {
  const errors: AgentSkillValidationError[] = [];
  for (const [key, value] of Object.entries(metadata)) {
    if (typeof value !== 'string') {
      errors.push({ field: `metadata.${key}`, message: 'metadata values must be strings.' });
    }
  }
  return errors;
}

// ---------------------------------------------------------------------------
// SKILL.md parser
// ---------------------------------------------------------------------------

export function parseSkillMd(content: string, skillDir = ''): AgentSkillParseResult {
  const errors: AgentSkillValidationError[] = [];
  const warnings: AgentSkillValidationError[] = [];

  // Extract frontmatter block
  const fmMatch = content.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!fmMatch) {
    return { errors: [{ field: 'frontmatter', message: 'SKILL.md must start with YAML frontmatter (---)' }], warnings };
  }

  const rawFrontmatter = fmMatch[1];
  const body = content.slice(fmMatch[0].length).trim();
  const parsed = parseFrontmatterYaml(rawFrontmatter);

  // Build frontmatter object
  const fm: AgentSkillFrontmatter = {
    name: String(parsed.name ?? ''),
    description: String(parsed.description ?? ''),
  };
  if (parsed.license) fm.license = String(parsed.license);
  if (parsed.compatibility) fm.compatibility = String(parsed.compatibility);
  if (parsed['allowed-tools']) {
    fm.allowedTools = String(parsed['allowed-tools']).split(',').map((s) => s.trim());
  }

  // Separate trainer.* metadata from unknown metadata
  const metadata: Record<string, string> = {};
  const unknownMetadata: Record<string, string> = {};
  if (parsed.metadata && typeof parsed.metadata === 'object') {
    for (const [key, value] of Object.entries(parsed.metadata)) {
      const strValue = String(value);
      metadata[key] = strValue;
      if (!key.startsWith(TRAINER_METADATA_PREFIX)) {
        unknownMetadata[key] = strValue;
      }
    }
    fm.metadata = metadata;
  }

  // Validate
  errors.push(...validateFrontmatter(fm));
  errors.push(...validateMetadata(fm.metadata ?? {}));

  // Resolve references from body
  const references: string[] = [];
  for (const m of body.matchAll(/\[([^\]]+)\]\(((?:references|assets|scripts)\/[^)]+)\)/g)) {
    references.push(m[2]);
  }

  return {
    skill: {
      frontmatter: fm,
      body,
      skillDir,
      references,
      rawFrontmatter,
      unknownMetadata,
    },
    errors,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// SKILL.md serializer (for export)
// ---------------------------------------------------------------------------

export function serializeSkillMd(skill: AgentSkill): string {
  const fm = skill.frontmatter;
  const lines: string[] = ['---'];
  lines.push(`name: ${fm.name}`);
  lines.push(`description: ${fm.description}`);
  if (fm.license) lines.push(`license: ${fm.license}`);
  if (fm.compatibility) lines.push(`compatibility: ${fm.compatibility}`);
  if (fm.metadata && Object.keys(fm.metadata).length > 0) {
    lines.push('metadata:');
    for (const [key, value] of Object.entries(fm.metadata)) {
      lines.push(`  ${key}: "${value}"`);
    }
  }
  if (fm.allowedTools?.length) {
    lines.push(`allowed-tools: ${fm.allowedTools.join(', ')}`);
  }
  lines.push('---');
  lines.push('');
  lines.push(skill.body);
  return lines.join('\n') + '\n';
}
