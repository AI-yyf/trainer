/**
 * CoachSkillRegistry (§三十一 §三十六 §五十五): unified skill discovery and
 * lifecycle management across multiple sources.
 *
 * Sources:
 *   built-in   — shipped with Trainer as standard SKILL.md directories
 *   user       — ~/.trainer/skills/<name>/SKILL.md
 *   project    — .agents/skills/<name>/SKILL.md (requires workspace trust)
 *   generated  — Trainer Skill Distillation output (lives in trainer data)
 *
 * A skill's lifecycle: candidate → draft → verified → active → deprecated.
 * Only `active` skills are visible to the coach agent by default.
 * Standard Agent Skills without trainer.* metadata work seamlessly.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CoachSkillSource = 'built-in' | 'user' | 'project' | 'generated';

export type CoachSkillLifecycle =
  | 'candidate'
  | 'draft'
  | 'verified'
  | 'active'
  | 'deprecated';

export interface CoachSkillRecord {
  /** Standard Agent Skill name (from SKILL.md frontmatter). */
  name: string;
  description: string;
  /** Which source this skill came from. */
  source: CoachSkillSource;
  /** Lifecycle stage. */
  lifecycle: CoachSkillLifecycle;
  /** Semantic version from metadata.trainer.version, or '0.0.0' for standard skills. */
  version: string;
  /** Absolute or relative path to the skill directory. */
  path: string;
  /** True if this skill has trainer.* metadata (Trainer Enhanced). */
  trainerEnhanced: boolean;
  /** True if the skill has scripts/ that require user approval. */
  hasScripts: boolean;
  /** True if the project source is trusted (only relevant for project source). */
  trusted: boolean;
  /** ISO timestamp of last modification. */
  updatedAt: string;
}

export interface CoachSkillQuery {
  source?: CoachSkillSource;
  lifecycle?: CoachSkillLifecycle;
  /** Case-insensitive substring match on name and description. */
  searchText?: string;
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export interface CoachSkillEntry {
  record: CoachSkillRecord;
  /** Parsed SKILL.md body (lazy — not loaded at discovery time, §八 Progressive Disclosure). */
  bodyLoader: () => string;
}

export class CoachSkillRegistry {
  private readonly entries = new Map<string, CoachSkillEntry>();

  /**
   * Register a skill. If a skill with the same name already exists:
   * - Higher lifecycle wins (active > verified > draft > candidate)
   * - Same lifecycle: newer updatedAt wins
   * Returns the registered record.
   */
  register(record: CoachSkillRecord, bodyLoader: () => string): CoachSkillRecord {
    const existing = this.entries.get(record.name);
    if (existing) {
      if (isHigherLifecycle(record.lifecycle, existing.record.lifecycle)) {
        this.entries.set(record.name, { record, bodyLoader });
        return record;
      }
      if (
        record.lifecycle === existing.record.lifecycle &&
        record.updatedAt > existing.record.updatedAt
      ) {
        this.entries.set(record.name, { record, bodyLoader });
        return record;
      }
      return existing.record;
    }
    this.entries.set(record.name, { record, bodyLoader });
    return record;
  }

  query(query: CoachSkillQuery = {}): CoachSkillRecord[] {
    let results = [...this.entries.values()].map((e) => e.record);
    if (query.source) {
      results = results.filter((r) => r.source === query.source);
    }
    if (query.lifecycle) {
      results = results.filter((r) => r.lifecycle === query.lifecycle);
    }
    if (query.searchText) {
      const needle = query.searchText.toLowerCase();
      results = results.filter(
        (r) =>
          r.name.toLowerCase().includes(needle) ||
          r.description.toLowerCase().includes(needle),
      );
    }
    return results.sort((a, b) => a.name.localeCompare(b.name));
  }

  get(name: string): CoachSkillEntry | undefined {
    return this.entries.get(name);
  }

  /** Get the SKILL.md body for a skill (§八 Progressive Disclosure — on demand). */
  loadBody(name: string): string | undefined {
    return this.entries.get(name)?.bodyLoader();
  }

  /** Active skills only (what the coach agent sees). */
  activeSkills(): CoachSkillRecord[] {
    return this.query().filter((r) => r.lifecycle === 'active');
  }

  size(): number {
    return this.entries.size;
  }
}

// ---------------------------------------------------------------------------
// Lifecycle helpers
// ---------------------------------------------------------------------------

const LIFECYCLE_ORDER: Record<CoachSkillLifecycle, number> = {
  candidate: 0,
  draft: 1,
  verified: 2,
  active: 3,
  deprecated: -1,
};

function isHigherLifecycle(a: CoachSkillLifecycle, b: CoachSkillLifecycle): boolean {
  return (LIFECYCLE_ORDER[a] ?? 0) > (LIFECYCLE_ORDER[b] ?? 0);
}

/** §五十七: a Coach Skill must have teaching value to be Trainer Enhanced. */
export function isTrainerEnhanced(metadata: Record<string, string> | undefined): boolean {
  if (!metadata) return false;
  return Boolean(
    metadata['trainer.skill-type'] === 'coach' ||
    metadata['trainer.pedagogy'] ||
    metadata['trainer.practice'] ||
    metadata['trainer.evaluation'],
  );
}

/** §六十六: scripts require explicit user approval — never auto-execute. */
export function hasExecutableScripts(references: string[]): boolean {
  return references.some((ref) => ref.startsWith('scripts/'));
}

/** §三十八: project skills are untrusted until workspace trust is confirmed. */
export function isProjectSkillTrusted(source: CoachSkillSource, workspaceTrusted: boolean): boolean {
  return source !== 'project' || workspaceTrusted;
}

/** §五十八 §五十九: teaching positioning filter — reject non-coaching skills. */
export function hasTeachingValue(metadata: Record<string, string> | undefined): boolean {
  if (!metadata) return false;
  return isTrainerEnhanced(metadata) || Boolean(metadata['trainer.skill-type']);
}
