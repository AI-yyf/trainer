'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  localizeTrainingNextHopLabel,
  resolveTrainingHandoff,
  resolveTrainingNextHop,
} = require('../dist/shared/src/trainingHandoffGovernance.js');

test('localizeTrainingNextHopLabel covers structured next-hop labels in every supported language', () => {
  const expected = {
    'zh-CN': ['已呈现', '继续计划', '项目子计划', '计划证据', '证据候选', '下一步已成形', '下一步目标已由结构化证据明确记录。'],
    'en-US': ['Surfaced', 'Continue in plan', 'Project subplan', 'Plan evidence', 'Evidence candidate', 'Next hop materialized', 'The next hop is recorded as structured evidence.'],
    'es-ES': ['Mostrado', 'Continuar en el plan', 'Subplan del proyecto', 'Evidencia del plan', 'Candidato de evidencia', 'Siguiente paso definido', 'El siguiente paso se registró como evidencia estructurada.'],
    'fr-FR': ['Affiché', 'Continuer dans le plan', 'Sous-plan du projet', 'Preuve du plan', 'Candidat de preuve', 'Prochaine étape définie', 'La prochaine étape est enregistrée comme preuve structurée.'],
    'de-DE': ['Angezeigt', 'Im Plan fortfahren', 'Projekt-Teilplan', 'Plan-Nachweis', 'Nachweis-Kandidat', 'Nächster Schritt festgelegt', 'Der nächste Schritt ist als strukturierter Nachweis erfasst.'],
    'ja-JP': ['表示済み', '計画を続ける', 'プロジェクトのサブプラン', '計画の証拠', '証拠候補', '次の一手を設定', '次の一手は構造化された証拠として記録されています。'],
    'ko-KR': ['표시됨', '계획에서 계속', '프로젝트 하위 계획', '계획 근거', '근거 후보', '다음 단계가 준비됨', '다음 단계가 구조화된 근거로 기록되었습니다.'],
    'pt-BR': ['Exibido', 'Continuar no plano', 'Subplano do projeto', 'Evidência do plano', 'Candidato de evidência', 'Próxima etapa definida', 'A próxima etapa foi registrada como evidência estruturada.'],
  };

  for (const [language, labels] of Object.entries(expected)) {
    assert.equal(localizeTrainingNextHopLabel(language, 'status', 'surfaced'), labels[0]);
    assert.equal(localizeTrainingNextHopLabel(language, 'continue_in', 'plan'), labels[1]);
    assert.equal(localizeTrainingNextHopLabel(language, 'project_scope', 'project_subplan'), labels[2]);
    assert.equal(localizeTrainingNextHopLabel(language, 'target_kind', 'plan_evidence'), labels[3]);
    assert.equal(localizeTrainingNextHopLabel(language, 'candidate_type', 'evidence_candidate'), labels[4]);
    assert.equal(localizeTrainingNextHopLabel(language, 'fallback_title'), labels[5]);
    assert.equal(localizeTrainingNextHopLabel(language, 'fallback_summary'), labels[6]);

    const resolved = resolveTrainingNextHop({
      language,
      latestTrainingNextHop: { status: 'surfaced' },
    });
    assert.equal(resolved.title, labels[5]);
    assert.equal(resolved.summary, labels[6]);
  }
});

test('localizeTrainingNextHopLabel keeps pending training states clear in every supported language', () => {
  const expected = {
    'zh-CN': '还需验证',
    'en-US': 'Needs a check',
    'es-ES': 'Pendiente de revisión',
    'fr-FR': 'À vérifier',
    'de-DE': 'Prüfung ausstehend',
    'ja-JP': '確認待ち',
    'ko-KR': '확인 대기',
    'pt-BR': 'Aguardando verificação',
  };

  for (const [language, label] of Object.entries(expected)) {
    assert.equal(localizeTrainingNextHopLabel(language, 'status', 'verification_required'), label);
  }

  const resolved = resolveTrainingNextHop({
    language: 'zh-CN',
    latestTrainingNextHop: {
      title: '核验当前练习',
      continueIn: 'training',
      status: 'verification_required',
    },
  });
  assert.equal(resolved.status, 'verification_required');
  assert.equal(resolved.canContinue, true);
});

test('resolveTrainingHandoff surfaces the same training card accepted from conversation', () => {
  const result = resolveTrainingHandoff({
    latestTrainingHandoff: {
      candidateId: 'candidate-training-1',
      candidateType: 'practice_candidate',
      targetKind: 'training_card',
      targetId: 'practice-response-model',
      continueIn: 'training',
      acceptedInto: 'training',
      handoffStatus: 'executed',
      handoffSummary: 'Accepted from chat and handed off into training.',
      coachOnly: true,
      cardType: 'practice',
      cardTitle: 'Recover response_model through one route',
      scenarioPack: 'remote_workspace',
      learnerDeliverables: ['Implement one route slice yourself.'],
      verificationSteps: ['Run one focused route verification.'],
      successSignal: 'The route passes one focused verification.',
      returnWith: 'Bring back the verification output plus one remaining question.',
      nextAfterCompletion: 'Record the verification evidence.',
      fallbackAction: 'Return to coach chat with the exact blocker.',
    },
    selectedCardId: 'practice-response-model',
    selectedCardType: 'practice',
    selectedCardTitle: 'Recover response_model through one route',
    trainingCardCandidates: [
      {
        id: 'practice-response-model',
        type: 'practice',
        title: 'Recover response_model through one route',
      },
    ],
    activeTrainingCardRouting: {
      selectedCardId: 'practice-response-model',
      selectedCard: {
        title: 'Recover response_model through one route',
        type: 'practice',
      },
      whyThisCard: 'This card unlocks the current FastAPI blocker.',
      blockedCandidates: [],
      fallbackAction: 'Bring the exact blocker back into coach chat.',
      candidateCount: 1,
      eligibleCount: 1,
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.source, 'training_handoff');
  assert.equal(result.selectedCardId, 'practice-response-model');
  assert.equal(result.selectedCardTitle, 'Recover response_model through one route');
  assert.equal(result.selectedCardType, 'practice');
  assert.equal(result.scenarioPack, 'remote_workspace');
  assert.equal(result.handoffStatus, 'executed');
  assert.equal(result.coachOnly, true);
  assert.match(result.whyThisCard, /FastAPI blocker/i);
  assert.deepEqual(result.learnerDeliverables, ['Implement one route slice yourself.']);
  assert.deepEqual(result.verificationSteps, ['Run one focused route verification.']);
  assert.match(result.returnWith, /verification output/i);
});

test('resolveTrainingHandoff explains blocked same-turn candidates when routing pauses them', () => {
  const result = resolveTrainingHandoff({
    latestTrainingHandoff: {
      candidateId: 'candidate-flash-1',
      candidateType: 'flash_candidate',
      targetKind: 'training_card',
      targetId: 'flash-depends',
      continueIn: 'training',
      acceptedInto: 'training',
      handoffStatus: 'executed',
      handoffSummary: 'Accepted from chat and handed off into training.',
      coachOnly: true,
      cardType: 'flash',
      cardTitle: 'Recall Depends boundary',
    },
    selectedCardId: 'flash-depends',
    selectedCardType: 'flash',
    activeTrainingCardRouting: {
      selectedCardId: 'flash-depends',
      selectedCard: {
        title: 'Recall Depends boundary',
        type: 'flash',
      },
      whyThisCard: 'Flash is the current deck, so practice stays deferred.',
      blockedCandidates: [
        {
          cardId: 'practice-unsafe',
          type: 'practice',
          title: 'Trainer edits the project directly',
          reasons: ['practice would cross the coach-only boundary'],
        },
      ],
      fallbackAction: 'Stay in coach chat and clarify the blocker.',
      candidateCount: 2,
      eligibleCount: 1,
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.blockedCount, 1);
  assert.equal(result.selectedCardTitle, 'Recall Depends boundary');
  assert.match(result.whyThisCard, /stays deferred/i);
  assert.match(result.blockedReason, /coach-only boundary/i);
});

test('resolveTrainingHandoff prefers the explicitly returned card over the newly routed next card', () => {
  const result = resolveTrainingHandoff({
    latestTrainingHandoff: {
      candidateId: 'candidate-flash-return-1',
      candidateType: 'flash_candidate',
      targetKind: 'training_card',
      targetId: 'flash-depends-old',
      continueIn: 'training',
      acceptedInto: 'training',
      handoffStatus: 'fed_back',
      handoffSummary: 'Brought the completed flash result back for coach judgment.',
      coachOnly: true,
      cardType: 'flash',
      cardTitle: 'Depends boundary recall',
      returnMode: 'result',
      returnSummary: 'Now explains when Depends belongs in the route.',
    },
    selectedCardId: 'flash-depends-old',
    selectedCardType: 'flash',
    selectedCardTitle: 'Depends boundary recall',
    activeTrainingCardRouting: {
      selectedCardId: 'flash-depends-next',
      selectedCard: {
        title: 'Next flash card that should stay in training',
        type: 'flash',
      },
      whyThisCard: 'A new flash candidate is ready, but the previous answer still needs coach judgment.',
      blockedCandidates: [],
      fallbackAction: 'Bring the judged result back before widening the deck.',
      candidateCount: 2,
      eligibleCount: 2,
    },
    trainingCardCandidates: [
      {
        id: 'flash-depends-old',
        type: 'flash',
        title: 'Depends boundary recall',
      },
      {
        id: 'flash-depends-next',
        type: 'flash',
        title: 'Next flash card that should stay in training',
      },
    ],
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.selectedCardId, 'flash-depends-old');
  assert.equal(result.selectedCardTitle, 'Depends boundary recall');
  assert.equal(result.targetId, 'flash-depends-old');
  assert.equal(result.selectedCardType, 'flash');
});

test('resolveTrainingHandoff ledger fallback still prefers explicit selected card identity', () => {
  const result = resolveTrainingHandoff({
    selectedCardId: 'flash-depends-answered',
    selectedCardType: 'flash',
    selectedCardTitle: 'Answered Depends card',
    activeTrainingCardRouting: {
      selectedCardId: 'flash-depends-next',
      selectedCard: {
        title: 'Next Depends card',
        type: 'flash',
      },
      whyThisCard: 'The deck already advanced to the next card.',
      blockedCandidates: [],
      fallbackAction: 'Return the answered card to coach first.',
      candidateCount: 2,
      eligibleCount: 2,
    },
    trainingEventLedger: [
      {
        eventType: 'active_card_selected',
        selectedCardId: 'flash-depends-next',
        selectedCardType: 'flash',
        selectedCardTitle: 'Next Depends card',
        whyThisCard: 'The deck already advanced to the next card.',
        scenarioPack: 'remote_workspace',
        createdAt: '2026-05-23T01:00:00.000Z',
      },
    ],
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.source, 'ledger');
  assert.equal(result.scenarioPack, 'remote_workspace');
  assert.equal(result.selectedCardId, 'flash-depends-answered');
  assert.equal(result.targetId, 'flash-depends-answered');
  assert.equal(result.selectedCardTitle, 'Answered Depends card');
  assert.equal(result.selectedCardType, 'flash');
});

test('resolveTrainingHandoff marks resource-risk blocked cards as paused', () => {
  const result = resolveTrainingHandoff({
    latestTrainingHandoff: {
      candidateId: 'candidate-practice-stale',
      candidateType: 'practice_candidate',
      targetKind: 'training_card',
      targetId: 'practice-stale-doc',
      continueIn: 'training',
      acceptedInto: 'training',
      handoffStatus: 'executed',
      handoffSummary: 'Accepted from chat and handed off into training.',
      coachOnly: true,
      cardType: 'practice',
      cardTitle: 'Rebuild API slice from doc',
    },
    activeTrainingCardRouting: {
      selectedCardId: undefined,
      whyThisCard: 'No eligible training card can be activated yet.',
      blockedCandidates: [
        {
          cardId: 'practice-stale-doc',
          type: 'practice',
          title: 'Rebuild API slice from doc',
          reasons: ['resource is not trusted or fresh enough'],
        },
      ],
      fallbackAction: 'Refresh the stale material first.',
      candidateCount: 1,
      eligibleCount: 0,
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.blockedDueToResourceRisk, true);
  assert.equal(result.pausedByResourceRisk, true);
  assert.match(result.resourceRiskReason, /trusted|fresh/i);
  assert.match(result.blockedReason, /trusted|fresh/i);
});

test('resolveTrainingNextHop surfaces governed evidence candidates that can continue into plan', () => {
  const result = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      candidateId: 'next-hop-evidence-1',
      candidateType: 'evidence_candidate',
      title: 'Adopt verified route output into plan evidence',
      summary: 'The current practice result is ready to be reviewed as formal plan evidence.',
      whyNow: 'This card already produced a verified result in the current project lane.',
      scenarioPack: 'remote_workspace',
      projectScope: 'project_subplan',
      continueIn: 'plan',
      targetKind: 'plan_evidence',
      targetId: 'plan-evidence-7',
      status: 'surfaced',
      planEvidenceId: 'plan-evidence-7',
      sourceChain: ['training_return', 'coach_judgment'],
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.source, 'latest_training_next_hop');
  assert.equal(result.canContinue, true);
  assert.equal(result.continueIn, 'plan');
  assert.equal(result.scenarioPack, 'remote_workspace');
  assert.equal(result.projectScope, 'project_subplan');
  assert.equal(result.planEvidenceId, 'plan-evidence-7');
  assert.deepEqual(result.sourceChain, ['training_return', 'coach_judgment']);
  assert.ok(result.title.length <= 54);
  assert.ok(result.whyNow.length <= 88);
});

test('resolveTrainingNextHop marks accepted and archived next hops as no longer continuable', () => {
  const accepted = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      title: 'Already absorbed into governed plan state',
      status: 'accepted',
      continueIn: 'plan',
    },
  });
  const archived = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      title: 'Archived flash recovery hop',
      status: 'archived',
      continueIn: 'training',
    },
  });

  assert.equal(accepted.shouldRender, true);
  assert.equal(accepted.hasRenderableCopy, true);
  assert.equal(accepted.hasStructuredTarget, true);
  assert.equal(accepted.canContinue, false);
  assert.equal(archived.shouldRender, true);
  assert.equal(archived.hasRenderableCopy, true);
  assert.equal(archived.hasStructuredTarget, true);
  assert.equal(archived.canContinue, false);
});

test('resolveTrainingNextHop stays hidden when no explicit next-hop object exists', () => {
  const result = resolveTrainingNextHop({ language: 'en-US' });

  assert.equal(result.shouldRender, false);
  assert.equal(result.hasRenderableCopy, false);
  assert.equal(result.hasStructuredTarget, false);
  assert.equal(result.canContinue, false);
  assert.equal(result.source, 'none');
  assert.deepEqual(result.sourceChain, []);
});

test('resolveTrainingNextHop stays hidden when only fallback copy exists without structured next-hop authority', () => {
  const result = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      title: 'Keep going from the current review note',
      summary: 'There is a sentence, but no governed next-hop target has been materialized yet.',
      whyNow: 'This should not light up next-hop visible truth on its own.',
    },
  });

  assert.equal(result.hasRenderableCopy, true);
  assert.equal(result.hasStructuredTarget, false);
  assert.equal(result.shouldRender, false);
  assert.equal(result.canContinue, false);
});

test('resolveTrainingNextHop keeps zh next-hop explanation compact and localized', () => {
  const result = resolveTrainingNextHop({
    language: 'zh-CN',
    latestTrainingNextHop: {
      title: '把这次 route 验证结果记成计划证据，再决定要不要补一张 response_model 闪记卡。',
      summary: '这次训练结果已经够进入计划证据审阅。',
      whyNow:
        '当前训练刚完成最小 route 契约切片，先让计划吸收这次证据，再决定是否需要补记忆强化，能避免连续跳视图造成理解断层。',
      status: 'surfaced',
      continueIn: 'plan',
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.hasRenderableCopy, true);
  assert.equal(result.hasStructuredTarget, true);
  assert.ok(result.title.length <= 54);
  assert.ok(result.whyNow.length <= 88);
  assert.doesNotMatch(result.title, /Candidate note|Waiting for/i);
});

test('resolveTrainingNextHop still renders structured installed-state truth when only structured next-hop authority exists', () => {
  const result = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      candidateId: 'practice-next-hop-1',
      candidateType: 'practice_candidate',
      continueIn: 'training',
      targetKind: 'training_card',
      targetId: 'vsix-next-hop-practice',
      status: 'surfaced',
      reviewArtifactId: 'review-artifact-installed-state',
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.hasStructuredTarget, true);
  assert.equal(result.hasRenderableCopy, true);
  assert.equal(result.canContinue, true);
  assert.equal(result.candidateType, 'practice_candidate');
  assert.equal(result.targetKind, 'training_card');
  assert.equal(result.targetId, 'vsix-next-hop-practice');
  assert.equal(result.reviewArtifactId, 'review-artifact-installed-state');
  assert.match(result.title, /next hop|continue/i);
});

test('resolveTrainingNextHop keeps successful practice returns pointed back to coach', () => {
  const result = resolveTrainingNextHop({
    language: 'en-US',
    latestTrainingNextHop: {
      candidateId: 'practice-return-chat-1',
      candidateType: 'practice_candidate',
      continueIn: 'chat',
      targetKind: 'training_card',
      targetId: 'practice-return-chat-1',
      status: 'continued_in_chat',
      handoffSummary: 'The card passed and now needs coach judgment.',
      nextAfterCompletion: 'Return to coach with the verified result.',
    },
  });

  assert.equal(result.shouldRender, true);
  assert.equal(result.hasStructuredTarget, true);
  assert.equal(result.continueIn, 'chat');
  assert.equal(result.status, 'continued_in_chat');
  assert.equal(result.canContinue, false);
  assert.match(
    `${result.title} ${result.summary ?? ''} ${result.nextAfterCompletion ?? ''}`,
    /coach judgment|return to coach/i,
  );
});

test('resolveTrainingNextHop falls back to training_next_hop_materialized ledger when latestTrainingNextHop is missing', () => {
  const result = resolveTrainingNextHop({
    language: 'en-US',
    trainingEventLedger: [
      {
        eventType: 'training_next_hop_materialized',
        candidateId: 'ledger-next-hop-1',
        candidateType: 'practice_candidate',
        candidateStatus: 'surfaced',
        scenarioPack: 'remote_workspace',
        candidateContinueIn: 'training',
        candidateTargetKind: 'training_card',
        candidateTargetId: 'vsix-next-hop-practice',
        candidateTitle: 'Continue with one narrower practice slice',
        candidateWhyNow: 'The previous result passed but still needs reinforcement.',
        reviewArtifactId: 'review-artifact-ledger-1',
        planEvidenceId: 'plan-evidence-ledger-1',
        selectedCardType: 'practice',
        selectedCardTitle: 'FastAPI Depends boundary minimum slice',
        nextAfterCompletion: 'Bring back one verification proof.',
        fallbackAction: 'Return to coach with the exact blocker.',
        sourceChain: ['training_return', 'coach_judgment'],
        createdAt: '2026-05-24T06:12:00.000Z',
      },
    ],
  });

  assert.equal(result.source, 'training_event_ledger');
  assert.equal(result.shouldRender, true);
  assert.equal(result.hasStructuredTarget, true);
  assert.equal(result.hasRenderableCopy, true);
  assert.equal(result.canContinue, true);
  assert.equal(result.candidateType, 'practice_candidate');
  assert.equal(result.scenarioPack, 'remote_workspace');
  assert.equal(result.targetKind, 'training_card');
  assert.equal(result.targetId, 'vsix-next-hop-practice');
  assert.equal(result.continueIn, 'training');
  assert.equal(result.status, 'surfaced');
  assert.equal(result.reviewArtifactId, 'review-artifact-ledger-1');
  assert.equal(result.planEvidenceId, 'plan-evidence-ledger-1');
  assert.deepEqual(result.sourceChain, ['training_return', 'coach_judgment']);
});
