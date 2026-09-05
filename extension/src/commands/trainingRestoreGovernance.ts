export type ExplicitRestoreTarget = 'theory_drill' | 'scenario_lab' | 'review_artifact';

export type ExplicitRestoreStep = {
  target: ExplicitRestoreTarget;
  requestPath:
    | '/training/theory-drill/restore'
    | '/training/scenario-lab/restore'
    | '/training/review-artifact/restore';
  body: Record<string, unknown>;
};

export type TrainingNextHopView = {
  candidateId?: string;
  candidateType?: string;
  continueIn?: string;
  targetKind?: string;
  targetId?: string;
  status?: string;
  reviewArtifactId?: string;
  nextAfterCompletion?: string;
  cardTitle?: string;
  summary?: string;
};

export function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
}

export function asNonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

export function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function buildMemorySummaryQueryPath(workspaceId: string, sessionId?: string): string {
  const params = new URLSearchParams();
  params.set('workspace_id', workspaceId);
  if (sessionId) {
    params.set('session_id', sessionId);
  }
  return `/memory/summary?${params.toString()}`;
}

export function resolveExplicitTrainingRestoreStepFromSummary(
  summary: unknown,
  payload: Record<string, unknown>,
  workspaceId: string,
): ExplicitRestoreStep | undefined {
  const target = payload.trainingRestoreTarget;
  if (
    target !== 'theory_drill' &&
    target !== 'scenario_lab' &&
    target !== 'review_artifact'
  ) {
    return undefined;
  }

  const memory = asRecord(asRecord(summary)?.memory);
  if (!memory) {
    return undefined;
  }

  const note = typeof payload.resumeReason === 'string' ? payload.resumeReason : '';
  const overrideEntryId = asNonEmptyString(payload.historyEntryId);
  const overrideVersion = asNumber(payload.historyVersion);

  if (target === 'theory_drill') {
    const theoryDrillId = asNonEmptyString(payload.theoryDrillId);
    const theoryDrillHistory = Array.isArray(memory.theory_drill_history)
      ? memory.theory_drill_history
      : [];
    const match = theoryDrillHistory.find((entry) => {
      const record = asRecord(entry);
      if (!record) {
        return false;
      }
      if (overrideEntryId) {
        const entryId = asNonEmptyString(record.entry_id) ?? asNonEmptyString(record.entryId);
        const version = asNumber(record.version);
        return entryId === overrideEntryId && (overrideVersion === undefined || version === overrideVersion);
      }
      if (!theoryDrillId) {
        return false;
      }
      const historyTheoryDrillId =
        asNonEmptyString(record.theory_drill_id) ?? asNonEmptyString(record.theoryDrillId);
      return historyTheoryDrillId === theoryDrillId;
    });
    const matchRecord = asRecord(match);
    const entryId = matchRecord
      ? asNonEmptyString(matchRecord.entry_id) ?? asNonEmptyString(matchRecord.entryId)
      : undefined;
    const version = matchRecord ? asNumber(matchRecord.version) : undefined;
    if (!theoryDrillId || !entryId) {
      return undefined;
    }
    return {
      target,
      requestPath: '/training/theory-drill/restore',
      body: {
        workspace_id: workspaceId,
        theory_drill_id: theoryDrillId,
        history_entry_id: entryId,
        history_version: version,
        note,
      },
    };
  }

  if (target === 'scenario_lab') {
    const scenarioLabId = asNonEmptyString(payload.scenarioLabId);
    const scenarioLabHistory = Array.isArray(memory.scenario_lab_history)
      ? memory.scenario_lab_history
      : [];
    const match = scenarioLabHistory.find((entry) => {
      const record = asRecord(entry);
      if (!record) {
        return false;
      }
      if (overrideEntryId) {
        const entryId = asNonEmptyString(record.entry_id) ?? asNonEmptyString(record.entryId);
        const version = asNumber(record.version);
        return entryId === overrideEntryId && (overrideVersion === undefined || version === overrideVersion);
      }
      if (!scenarioLabId) {
        return false;
      }
      const historyScenarioLabId =
        asNonEmptyString(record.scenario_lab_id) ?? asNonEmptyString(record.scenarioLabId);
      return historyScenarioLabId === scenarioLabId;
    });
    const matchRecord = asRecord(match);
    const entryId = matchRecord
      ? asNonEmptyString(matchRecord.entry_id) ?? asNonEmptyString(matchRecord.entryId)
      : undefined;
    const version = matchRecord ? asNumber(matchRecord.version) : undefined;
    if (!scenarioLabId || !entryId) {
      return undefined;
    }
    return {
      target,
      requestPath: '/training/scenario-lab/restore',
      body: {
        workspace_id: workspaceId,
        scenario_lab_id: scenarioLabId,
        history_entry_id: entryId,
        history_version: version,
        note,
      },
    };
  }

  const reviewArtifactId = asNonEmptyString(payload.reviewArtifactId);
  const reviewArtifactHistory = Array.isArray(memory.review_artifact_history)
    ? memory.review_artifact_history
    : [];
  const match = reviewArtifactHistory.find((entry) => {
    const record = asRecord(entry);
    if (!record) {
      return false;
    }
    if (overrideEntryId) {
      const entryId = asNonEmptyString(record.entry_id) ?? asNonEmptyString(record.entryId);
      const version = asNumber(record.version);
      return entryId === overrideEntryId && (overrideVersion === undefined || version === overrideVersion);
    }
    if (!reviewArtifactId) {
      return false;
    }
    const historyReviewArtifactId =
      asNonEmptyString(record.review_artifact_id) ?? asNonEmptyString(record.reviewArtifactId);
    return historyReviewArtifactId === reviewArtifactId;
  });
  const matchRecord = asRecord(match);
  const entryId = matchRecord
    ? asNonEmptyString(matchRecord.entry_id) ?? asNonEmptyString(matchRecord.entryId)
    : undefined;
  const version = matchRecord ? asNumber(matchRecord.version) : undefined;
  if (!reviewArtifactId || !entryId) {
    return undefined;
  }
  return {
    target,
    requestPath: '/training/review-artifact/restore',
    body: {
      workspace_id: workspaceId,
      review_artifact_id: reviewArtifactId,
      history_entry_id: entryId,
      history_version: version,
      note,
    },
  };
}

export function resolveLatestTrainingNextHopFromSummary(
  summary: unknown,
): TrainingNextHopView | undefined {
  const memoryRecord = asRecord(asRecord(summary)?.memory);
  const workspaceRecord = asRecord(memoryRecord?.workspace);
  const rawNextHop = asRecord(workspaceRecord?.latest_training_next_hop);

  let nextHop = rawNextHop && Object.keys(rawNextHop).length > 0 ? rawNextHop : undefined;

  if (!nextHop && Array.isArray(memoryRecord?.training_event_ledger)) {
    const ledger = memoryRecord.training_event_ledger as Array<Record<string, unknown>>;
    const hopEvent = [...ledger].reverse().find(
      (event) =>
        event.event_type === 'training_next_hop_materialized' ||
        event.candidate_id,
    );
    if (hopEvent) {
      nextHop = {
        candidate_id: hopEvent.candidate_id,
        candidate_type: hopEvent.candidate_type,
        continue_in: hopEvent.candidate_continue_in ?? hopEvent.continue_in,
        target_kind: hopEvent.candidate_target_kind ?? hopEvent.target_kind,
        target_id: hopEvent.candidate_target_id ?? hopEvent.target_id,
        status: hopEvent.candidate_status ?? hopEvent.status ?? hopEvent.status_kind,
        review_artifact_id: hopEvent.review_artifact_id,
        next_after_completion: hopEvent.next_after_completion,
        card_title: hopEvent.candidate_title,
        status_summary: hopEvent.status_summary,
      };
    }
  }

  if (!nextHop) {
    return undefined;
  }

  return {
    candidateId: asNonEmptyString(nextHop.candidate_id),
    candidateType: asNonEmptyString(nextHop.candidate_type),
    continueIn: asNonEmptyString(nextHop.continue_in),
    targetKind: asNonEmptyString(nextHop.target_kind),
    targetId: asNonEmptyString(nextHop.target_id),
    status: asNonEmptyString(nextHop.status),
    reviewArtifactId: asNonEmptyString(nextHop.review_artifact_id),
    nextAfterCompletion: asNonEmptyString(nextHop.next_after_completion),
    cardTitle: asNonEmptyString(nextHop.card_title),
    summary: asNonEmptyString(nextHop.status_summary),
  };
}
