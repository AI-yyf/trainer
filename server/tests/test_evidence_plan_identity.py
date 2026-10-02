"""Evidence adoption keeps a live formal plan visible through hydrate and restart."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import EvidenceItem, LearningPlan, PlanStage
from app.core.settings import AppSettings
from app.main import create_app


@pytest.mark.parametrize('stage_bound,frozen', [(False, False), (True, False), (False, True)])
def test_adopted_evidence_preserves_formal_identity_across_restart(tmp_path: Path, stage_bound: bool, frozen: bool):
    settings = AppSettings(app_name='Evidence identity', host='127.0.0.1', port=8765,
        default_session_stage='intake', summary_message_limit=6,
        data_dir=tmp_path, database_name='trainer.db', enable_network_fetch=False)
    app = create_app(settings)
    workspace = 'evidence-plan-identity'
    plan = LearningPlan(id='plan-existing', title='Python nested objects', frozen=frozen,
        current_stage_id='stage-1', current_step='Run the tuple boundary test',
        next_after_current='Explain the nested mutation', blocked_reason='Old failing check',
        stages=[PlanStage(id='stage-1', title='Verify', goal='Run the tuple boundary test', status='active', outcomes=['Expected TypeError is caught']),
            PlanStage(id='stage-2', title='Apply', goal='Implement the nested sum', status='pending',
                outcomes=['Empty input returns zero'])])
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime.repository.save_plan(workspace, plan)
        runtime.memory_service.persist_plan_runtime_recovery(workspace, plan=plan,
            plan_runtime={'current_step': plan.current_step, 'resume_state': 'waiting',
                'next_after_current': plan.next_after_current}, request_id='plan-start')
        started = client.post('/session/start', json={'workspace_id': workspace, 'workspace_name': 'Python'})
        assert started.status_code == 200
        assert started.json()['plan']['id'] == plan.id
        evidence = runtime.memory_service.enqueue_evidence(workspace,
            EvidenceItem(summary='pytest: 1 passed', source='training_handoff_return', outcome='pass',
                target_plan_stage_id='stage-1' if stage_bound else ''),
            verified=True, verification_source='test_runner')
        adopted = client.post('/evidence/adopt', json={'workspace_id': workspace, 'evidence_id': evidence.id})
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()['plan_updated'] is (not frozen)
        after = client.get('/memory/summary', params={'workspace_id': workspace}).json()
        assert after['plan'] is not None, after
        assert after['plan']['id'] == plan.id
        runtime_step = after['memory']['workspace']['latest_plan_runtime']['current_step']
        assert after['plan']['current_step'] == runtime_step
        expected_step = plan.current_step if frozen else (
            'Implement the nested sum' if stage_bound else 'Explain the nested mutation')
        assert runtime_step == expected_step
        assert after['plan']['current_stage_id'] == ('stage-2' if stage_bound else 'stage-1')
        if not frozen:
            assert not after['plan']['blocked_reason']
    with TestClient(create_app(settings)) as restarted:
        restored = restarted.get('/memory/summary', params={'workspace_id': workspace}).json()
        assert restored['plan']['id'] == plan.id
        assert restored['plan']['current_step'] == expected_step
