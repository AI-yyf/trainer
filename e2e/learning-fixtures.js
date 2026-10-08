// A plan-only journey starts without an unfinished practice attempt. The
// shared preview seed also contains an active card; retaining it would test
// the separate continue-practice priority instead of the plan decision.
function planOnlyFixture(source) {
  const workspace = { ...source.memory.workspace };
  for (const key of ['latestTrainingHandoff', 'latestTrainingNextHop', 'liveTrainingSelection', 'latestConversationHandoff']) {
    delete workspace[key];
  }
  return { ...source, memory: { ...source.memory, workspace },
    workspaceTrainingState: { workspaceId: workspace.workspaceId, trainingCardCandidates: [],
      dueReviews: source.workspaceTrainingState?.dueReviews ?? [] },
  };
}

async function applyPlanOnlyFixture(page) {
  const source = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const payload = planOnlyFixture(source);
  await page.evaluate(payload => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload }), payload);
}

module.exports = { planOnlyFixture, applyPlanOnlyFixture };
