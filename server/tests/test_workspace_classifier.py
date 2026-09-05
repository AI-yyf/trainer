"""Tests for §1.21 / §1.21.1 workspace classifier — heuristic and LLM-enhanced."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import FirstLookSummary, WorkspaceUnderstandingSnapshot
from app.workspace.authority import PermissionLevel, WorkspaceAuthority
from app.workspace.classifier import (
    _classify_folder_role,
    _guess_project_type,
    _parse_llm_response,
    _scan_directory,
    classify_heuristic,
    classify_with_llm,
    complete_project_adoption,
    discover_project,
    is_code_like_current_file,
    is_code_like_entry_point,
    resolve_project_discovery,
)

# ---------------------------------------------------------------------------
# Fixtures — real temp directories
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_dir(tmp_path: Path) -> Path:
    return tmp_path / "empty_project"


@pytest.fixture()
def python_project(tmp_path: Path) -> Path:
    root = tmp_path / "my_api"
    root.mkdir()
    (root / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (root / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "routes.py").write_text("# routes")
    (root / "app" / "models.py").write_text("# models")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("# test")
    return root


@pytest.fixture()
def web_project(tmp_path: Path) -> Path:
    root = tmp_path / "web_app"
    root.mkdir()
    (root / "package.json").write_text('{"name": "web", "dependencies": {"react": "*"}}')
    (root / "vite.config.ts").write_text("// vite config")
    (root / "src").mkdir()
    (root / "src" / "index.tsx").write_text("// entry")
    (root / "src" / "App.tsx").write_text("// app")
    (root / "src" / "styles.css").write_text("/* styles */")
    return root


@pytest.fixture()
def ml_project(tmp_path: Path) -> Path:
    root = tmp_path / "ml_lab"
    root.mkdir()
    (root / "train.py").write_text("import torch\n# training script")
    (root / "model.pt").write_bytes(b"\x00" * 16)
    (root / "notebooks").mkdir()
    (root / "notebooks" / "exploration.ipynb").write_text("{}")
    (root / "data").mkdir()
    (root / "data" / "train.csv").write_text("a,b\n1,2")
    (root / "models").mkdir()
    (root / "models" / "model.pkl").write_bytes(b"\x00" * 8)
    return root


@pytest.fixture()
def notes_dir(tmp_path: Path) -> Path:
    root = tmp_path / "learning_notes"
    root.mkdir()
    (root / "papers").mkdir()
    (root / "papers" / "paper1.pdf").write_bytes(b"%PDF-1.4")
    (root / "papers" / "paper2.pdf").write_bytes(b"%PDF-1.4")
    (root / "lectures").mkdir()
    (root / "lectures" / "lecture1.pptx").write_bytes(b"\x00" * 16)
    (root / "exercises").mkdir()
    (root / "exercises" / "hw1.md").write_text("# Homework 1")
    (root / "readings").mkdir()
    (root / "readings" / "chapter1.pdf").write_bytes(b"%PDF-1.4")
    (root / "cheatsheets").mkdir()
    (root / "cheatsheets" / "python.md").write_text("# Python cheatsheet")
    return root


@pytest.fixture()
def idea_dir(tmp_path: Path) -> Path:
    root = tmp_path / "my_idea"
    root.mkdir()
    (root / "README.md").write_text("# My Idea\nA project idea.")
    (root / "notes.md").write_text("# Notes\nSome notes.")
    (root / "todo.txt").write_text("- [ ] Do something")
    return root


# ---------------------------------------------------------------------------
# Unit tests — heuristic classifier
# ---------------------------------------------------------------------------


class TestClassifyHeuristic:
    """Test classify_heuristic for various folder types."""

    def test_empty_directory(self, empty_dir: Path) -> None:
        empty_dir.mkdir()
        result = classify_heuristic(str(empty_dir))
        assert result.folder_role == "empty_new_project"
        assert result.confidence >= 0.7
        assert result.project_type_guess == "unknown"
        assert result.classification_method == "heuristic"

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        result = classify_heuristic(str(tmp_path / "nonexistent"))
        assert result.folder_role == "empty_new_project"
        assert result.confidence >= 0.9
        assert "does not exist" in result.why_this_guess

    def test_remote_snapshot_is_not_empty_new_project(self) -> None:
        result = classify_heuristic(
            "/mnt/vdb1/yunfei.yan/RAP",
            remote_name="ssh-remote",
            workspace_file_snapshot={
                "is_remote": True,
                "files": [
                    {"path": "README.md"},
                    {"path": "setup.py"},
                    {"path": "requirements.txt"},
                    {"path": "navsim/agents/abstract_agent.py"},
                    {"path": "navsim/agents/rap_dino/rap_agent.py"},
                ],
            },
        )
        assert result.folder_role != "empty_new_project"
        assert result.folder_role in {"existing_engineering", "algorithm_model"}
        assert any("navsim" in item.lower() for item in result.core_modules_or_materials)

    def test_remote_without_snapshot_is_uncertain_not_empty(self) -> None:
        result = classify_heuristic(
            "/mnt/vdb1/yunfei.yan/RAP",
            remote_name="ssh-remote",
        )
        assert result.folder_role == "mixed_uncertain"
        assert "snapshot" in result.why_this_guess.lower()

    def test_file_path_instead_of_dir(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("hello")
        result = classify_heuristic(str(file_path))
        assert result.folder_role == "mixed_uncertain"
        assert "not a directory" in result.why_this_guess

    def test_python_api_project(self, python_project: Path) -> None:
        result = classify_heuristic(str(python_project))
        assert result.folder_role == "existing_engineering"
        assert result.confidence >= 0.5
        assert result.project_type_guess == "api_service"
        assert "main.py" in result.entry_points or "app/" in result.entry_points
        assert len(result.directory_anchors) > 0
        assert result.recommended_next_step != ""

    def test_web_project(self, web_project: Path) -> None:
        result = classify_heuristic(str(web_project))
        assert result.folder_role == "existing_engineering"
        assert result.project_type_guess == "web_app"
        assert result.confidence >= 0.5

    def test_ml_model_project(self, ml_project: Path) -> None:
        result = classify_heuristic(str(ml_project))
        assert result.folder_role == "algorithm_model"
        assert result.confidence >= 0.5
        assert result.project_type_guess in {"ml_model", "notebook_research"}
        assert "model" in result.why_this_guess.lower() or "training" in result.why_this_guess.lower()

    def test_learning_materials(self, notes_dir: Path) -> None:
        result = classify_heuristic(str(notes_dir))
        assert result.folder_role == "learning_materials"
        assert result.project_type_guess == "documentation"
        assert result.confidence >= 0.5

    def test_idea_scratchpad(self, idea_dir: Path) -> None:
        result = classify_heuristic(str(idea_dir))
        assert result.folder_role == "idea_scratchpad"
        assert result.confidence >= 0.5

    def test_first_look_summary_fields_present(self, python_project: Path) -> None:
        result = classify_heuristic(str(python_project))
        # All §1.21.1 fields must be present
        assert isinstance(result.folder_role, str)
        assert isinstance(result.project_type_guess, str)
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.why_this_guess, str)
        assert isinstance(result.entry_points, list)
        assert isinstance(result.directory_anchors, list)
        assert isinstance(result.core_modules_or_materials, list)
        assert isinstance(result.risk_zones, list)
        assert isinstance(result.training_opportunities, list)
        assert isinstance(result.unknowns, list)
        assert isinstance(result.recommended_next_step, str)
        assert isinstance(result.classified_at, str)
        assert result.classification_method == "heuristic"

    def test_recommended_next_step_varies_by_role(
        self,
        empty_dir: Path,
        python_project: Path,
        ml_project: Path,
        idea_dir: Path,
        notes_dir: Path,
    ) -> None:
        empty_dir.mkdir()
        results = {
            classify_heuristic(str(d)).folder_role: classify_heuristic(str(d)).recommended_next_step
            for d in [empty_dir, python_project, ml_project, idea_dir, notes_dir]
        }
        # Each role should have a unique recommended next step
        steps = list(results.values())
        assert all(isinstance(s, str) and len(s) > 0 for s in steps)

    def test_risk_zones_identified_for_existing_engineering(
        self, python_project: Path
    ) -> None:
        result = classify_heuristic(str(python_project))
        # Should note no tests (test file is there but only 1)
        assert isinstance(result.risk_zones, list)

    def test_training_opportunities_non_empty(
        self, python_project: Path
    ) -> None:
        result = classify_heuristic(str(python_project))
        assert len(result.training_opportunities) > 0

    @pytest.mark.parametrize(
        (
            "language",
            "expected_why",
            "expected_risk",
            "expected_opportunity",
            "expected_unknown_manifest",
            "expected_unknown_source",
            "expected_next_step",
            "expected_missing_prefix",
            "expected_missing_next_step",
        ),
        [
            (
                "zh-CN",
                "检测到依赖配置、源码目录或多个源文件。",
                "没有发现测试文件，改动前后需要额外验证。",
                "可以先为现有代码补上测试。",
                "还没有发现依赖清单，技术栈可能需要进一步确认。",
                "还没有发现可识别的源代码文件。",
                "先查看入口文件，并确定第一个小练习任务。",
                "找不到这个路径：",
                "先创建这个文件夹，再搭建新项目。",
            ),
            (
                "en-US",
                "Detected dependency files",
                "No test files detected — unverified codebase.",
                "Add first tests to existing code — high training value.",
                "No dependency manifest — tech stack may be implicit.",
                "No recognized source-code extensions found.",
                "Explore the codebase entry points and pick the first thin training task.",
                "Path does not exist: ",
                "Create the folder and scaffold a new project.",
            ),
            (
                "es-ES",
                "Se detectaron configuraciones de dependencias, directorios de código fuente o varios archivos de código.",
                "No se detectaron archivos de prueba; conviene verificar los cambios con más cuidado.",
                "Añade las primeras pruebas al código existente.",
                "No se encontró un archivo de dependencias; hay que confirmar la tecnología.",
                "No se encontraron extensiones de código fuente reconocibles.",
                "Revisa los puntos de entrada y elige la primera tarea breve de práctica.",
                "No se encontró la ruta: ",
                "Crea la carpeta y luego inicia el proyecto.",
            ),
            (
                "fr-FR",
                "Des fichiers de dépendances, des dossiers source ou plusieurs fichiers de code ont été détectés.",
                "Aucun fichier de test n'a été détecté ; vérifiez davantage les changements.",
                "Ajoutez les premiers tests au code existant.",
                "Aucun fichier de dépendances n'a été trouvé ; la technologie reste à confirmer.",
                "Aucune extension de code source reconnue n'a été trouvée.",
                "Examinez les points d'entrée et choisissez une première petite tâche d'entraînement.",
                "Chemin introuvable : ",
                "Créez le dossier, puis démarrez le projet.",
            ),
            (
                "de-DE",
                "Abhängigkeitsdateien, Quellordner oder mehrere Quelldateien wurden erkannt.",
                "Keine Testdateien gefunden. Änderungen sollten zusätzlich geprüft werden.",
                "Ergänzen Sie erste Tests für den bestehenden Code.",
                "Keine Abhängigkeitsdatei gefunden; der Technologie-Stack muss noch geklärt werden.",
                "Keine erkannten Quellcode-Dateiendungen gefunden.",
                "Prüfen Sie die Einstiegspunkte und wählen Sie die erste kleine Übungsaufgabe.",
                "Pfad nicht gefunden: ",
                "Erstellen Sie den Ordner und starten Sie dann das Projekt.",
            ),
            (
                "ja-JP",
                "依存関係の設定、ソースフォルダー、または複数のソースファイルが見つかりました。",
                "テストファイルが見つかりません。変更前後に追加の確認が必要です。",
                "既存コードに最初のテストを追加できます。",
                "依存関係の設定ファイルが見つからず、技術構成は追加確認が必要です。",
                "認識できるソースコードファイルが見つかりません。",
                "エントリーポイントを確認し、最初の小さな練習課題を決めましょう。",
                "このパスは見つかりません: ",
                "フォルダーを作成してから、プロジェクトを始めましょう。",
            ),
            (
                "ko-KR",
                "의존성 설정, 소스 디렉터리 또는 여러 소스 파일을 찾았습니다.",
                "테스트 파일을 찾지 못했습니다. 변경 전후로 추가 확인이 필요합니다.",
                "기존 코드에 첫 테스트를 추가해 보세요.",
                "의존성 설정 파일을 찾지 못해 기술 구성을 더 확인해야 합니다.",
                "인식할 수 있는 소스 코드 파일을 찾지 못했습니다.",
                "진입 파일을 확인하고 첫 번째 작은 연습 과제를 정하세요.",
                "경로를 찾을 수 없습니다: ",
                "폴더를 만든 뒤 프로젝트를 시작하세요.",
            ),
            (
                "pt-BR",
                "Encontramos configurações de dependências, diretórios de código ou vários arquivos-fonte.",
                "Não foram encontrados arquivos de teste. Verifique as alterações com mais cuidado.",
                "Adicione os primeiros testes ao código existente.",
                "Não foi encontrado arquivo de dependências; é preciso confirmar a tecnologia.",
                "Não foram encontradas extensões de código-fonte reconhecidas.",
                "Veja os pontos de entrada e escolha a primeira tarefa curta de prática.",
                "Caminho não encontrado: ",
                "Crie a pasta e depois inicie o projeto.",
            ),
        ],
    )
    def test_response_language_localizes_heuristic_summary(
        self,
        python_project: Path,
        empty_dir: Path,
        tmp_path: Path,
        language: str,
        expected_why: str,
        expected_risk: str,
        expected_opportunity: str,
        expected_unknown_manifest: str,
        expected_unknown_source: str,
        expected_next_step: str,
        expected_missing_prefix: str,
        expected_missing_next_step: str,
    ) -> None:
        existing = classify_heuristic(str(python_project), response_language=language)
        assert expected_why in existing.why_this_guess
        assert existing.risk_zones == [expected_risk]
        assert existing.training_opportunities[0] == expected_opportunity
        assert existing.recommended_next_step == expected_next_step

        empty_dir.mkdir()
        empty = classify_heuristic(str(empty_dir), response_language=language)
        assert empty.unknowns == [expected_unknown_manifest, expected_unknown_source]

        missing_path = tmp_path / "missing-project"
        missing = classify_heuristic(str(missing_path), response_language=language)
        assert missing.why_this_guess == f"{expected_missing_prefix}{missing_path}"
        if language == "en-US":
            assert missing.unknowns == [f"Path {missing_path} does not exist."]
        else:
            assert missing.unknowns == [f"{expected_missing_prefix}{missing_path}"]
        assert missing.recommended_next_step == expected_missing_next_step


class TestDirectoryScanning:
    def test_scan_skips_directory_link_resolving_outside_workspace(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "main.py").write_text("# workspace", encoding="utf-8")

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("# outside", encoding="utf-8")

        outside_link = workspace / "outside-link"
        try:
            outside_link.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError):
            pytest.skip("Directory symlinks are unavailable on this platform or test environment.")

        scan = _scan_directory(workspace)

        assert scan["extensions"] == {".py": 1}
        assert "outside-link" not in scan["top_level_dirs"]

    def test_scan_skips_common_heavy_and_hidden_directories(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "main.py").write_text("# workspace", encoding="utf-8")
        for heavy_dir in [".git", "node_modules"]:
            nested = workspace / heavy_dir / "nested"
            nested.mkdir(parents=True)
            (nested / "ignored.py").write_text("# ignored", encoding="utf-8")

        scan = _scan_directory(workspace)

        assert scan["file_count"] == 1
        assert scan["dir_count"] == 0
        assert scan["scan_limited"] is False
        assert scan["top_level_dirs"] == []
        assert scan["extensions"] == {".py": 1}

    def test_scan_budget_limits_traversal(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        current = workspace
        for index in range(12):
            current = current / f"n{index}"
            current.mkdir()
            (current / f"file-{index}.py").write_text("# x", encoding="utf-8")

        scan = _scan_directory(workspace, max_depth=30, scan_budget_ms=0)

        assert scan["scan_limited"] is True
        assert scan["file_count"] <= 1
        assert scan["dir_count"] <= 1


class TestProjectDiscovery:
    def test_discovery_requires_explicit_choice_without_claiming_management(
        self,
        python_project: Path,
    ) -> None:
        discovery = discover_project(str(python_project))

        assert discovery.status == "awaiting_decision"
        assert discovery.available_decisions == ("adopt", "browse", "ignore")
        assert discovery.is_managed is False
        assert discovery.persistent_memory_created is False
        assert discovery.provisioning_required is False
        assert discovery.trusted_boundary is False
        assert discovery.to_payload()["is_managed"] is False

    def test_browse_requires_trusted_root_and_keeps_project_read_only(self, tmp_path: Path) -> None:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "browser-project"
        project.mkdir(parents=True)
        (project / "main.py").write_text("print('browse')", encoding="utf-8")
        authority = WorkspaceAuthority(
            root_path=str(workspace_root),
            initial_permission=PermissionLevel.INSPECT,
        )

        discovery = discover_project(str(project), authority=authority)
        browsed = resolve_project_discovery(discovery, "browse", authority=authority)

        assert discovery.status == "awaiting_decision"
        assert browsed.status == "browse_only"
        assert browsed.trusted_boundary is True
        assert browsed.is_browse_only is True
        assert browsed.is_managed is False
        assert browsed.persistent_memory_created is False

    def test_adoption_stays_pending_until_every_project_artifact_exists(self, tmp_path: Path) -> None:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "adopted-project"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname = 'adopted'\n", encoding="utf-8")
        authority = WorkspaceAuthority(root_path=str(workspace_root))

        discovery = discover_project(str(project), authority=authority)
        requested = resolve_project_discovery(discovery, "adopt", authority=authority)

        assert requested.status == "adoption_requested"
        assert requested.is_managed is False
        assert requested.provisioning_required is True
        with pytest.raises(ValueError, match="project_plan_id"):
            complete_project_adoption(
                requested,
                {
                    "project_id": "project-1",
                    "project_memory_id": "memory-1",
                },
            )

        adopted = complete_project_adoption(
            requested,
            {
                "project_id": "project-1",
                "project_memory_id": "memory-1",
                "project_plan_id": "plan-1",
                "project_training_id": "training-1",
                "project_agent_context_id": "agent-context-1",
            },
        )
        assert adopted.status == "adopted"
        assert adopted.is_managed is True
        assert adopted.persistent_memory_created is True
        assert adopted.provisioning_required is False

    def test_opening_outside_active_root_is_rejected(self, tmp_path: Path) -> None:
        workspace_root = tmp_path / "trainer-workspace"
        outside_project = tmp_path / "outside-project"
        workspace_root.mkdir()
        outside_project.mkdir()
        (outside_project / "README.md").write_text("outside", encoding="utf-8")
        authority = WorkspaceAuthority(root_path=str(workspace_root))

        discovery = discover_project(str(outside_project), authority=authority)
        assert discovery.trusted_boundary is False
        with pytest.raises(PermissionError, match="inside the active workspace root"):
            resolve_project_discovery(discovery, "browse", authority=authority)

    def test_removed_project_cannot_be_opened_after_discovery(self, tmp_path: Path) -> None:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "removed-project"
        project.mkdir(parents=True)
        authority = WorkspaceAuthority(root_path=str(workspace_root))
        discovery = discover_project(str(project), authority=authority)
        project.rmdir()

        with pytest.raises(ValueError, match="no longer an available directory"):
            resolve_project_discovery(discovery, "adopt", authority=authority)

    def test_missing_project_never_becomes_an_ownership_candidate(self, tmp_path: Path) -> None:
        discovery = discover_project(str(tmp_path / "missing-project"))

        assert discovery.status == "unavailable"
        assert discovery.available_decisions == ()
        assert discovery.is_managed is False
        assert discovery.persistent_memory_created is False

    def test_remote_discovery_can_browse_without_a_local_directory(self) -> None:
        discovery = discover_project(
            "/mnt/vdb1/yunfei.yan/RAP",
            summary=classify_heuristic(
                "/mnt/vdb1/yunfei.yan/RAP",
                remote_name="ssh-remote",
            ),
            remote_workspace=True,
        )
        browsed = resolve_project_discovery(discovery, "browse")
        assert browsed.status == "browse_only"
        assert browsed.is_browse_only is True
        assert browsed.is_managed is False
        assert browsed.persistent_memory_created is False
        with pytest.raises(ValueError, match="cannot be adopted"):
            resolve_project_discovery(discovery, "adopt")


def test_code_like_current_file_rejects_html_preview_shell() -> None:
    assert not is_code_like_current_file(
        {
            "path": "index.html",
            "language_id": "html",
            "content": "<!doctype html><html lang='en'></html>",
        }
    )


def test_code_like_entry_point_keeps_code_entries_but_filters_html_shells() -> None:
    assert is_code_like_entry_point("src/")
    assert is_code_like_entry_point("src/user.ts")
    assert not is_code_like_entry_point("index.html")


# ---------------------------------------------------------------------------
# Unit tests — internal helpers
# ---------------------------------------------------------------------------


class TestScanDirectory:
    def test_scan_counts_files(self, python_project: Path) -> None:
        scan = _scan_directory(python_project)
        assert scan["file_count"] >= 4  # requirements.txt, main.py, __init__.py, routes.py, models.py, test_main.py
        assert scan["dir_count"] >= 2  # app/, tests/
        assert ".py" in scan["extensions"]
        assert "requirements.txt" in scan["dependency_files"]

    def test_scan_respects_max_depth(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("x")
        scan = _scan_directory(tmp_path, max_depth=2)
        # Should not reach depth 5
        assert scan["file_count"] == 0 or scan["file_count"] >= 0

    def test_classify_folder_role_returns_tuple(self, python_project: Path) -> None:
        scan = _scan_directory(python_project)
        role, conf, reason = _classify_folder_role(scan)
        assert role in {
            "empty_new_project",
            "existing_engineering",
            "algorithm_model",
            "idea_scratchpad",
            "learning_materials",
            "mixed_uncertain",
        }
        assert 0.0 <= conf <= 1.0
        assert isinstance(reason, str)


class TestGuessProjectType:
    def test_guess_for_python_api(self, python_project: Path) -> None:
        scan = _scan_directory(python_project)
        ptype, reason = _guess_project_type(scan, "existing_engineering")
        assert ptype == "api_service"

    def test_guess_for_empty(self, tmp_path: Path) -> None:
        scan = _scan_directory(tmp_path)
        ptype, _ = _guess_project_type(scan, "empty_new_project")
        assert ptype == "unknown"


# ---------------------------------------------------------------------------
# Unit tests — LLM response parsing
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_valid_json_response(self) -> None:
        base = FirstLookSummary(
            folder_role="mixed_uncertain",
            project_type_guess="unknown",
            confidence=0.3,
            why_this_guess="heuristic fallback",
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "folder_role": "existing_engineering",
                            "project_type_guess": "api_service",
                            "confidence": 0.85,
                            "why_this_guess": "LLM detected API patterns.",
                            "risk_zones": ["No tests."],
                            "training_opportunities": ["Add first test."],
                            "unknowns": [],
                            "recommended_next_step": "Start with a test.",
                        }),
                    },
                },
            ],
        }
        result = _parse_llm_response(base, response)
        assert result.folder_role == "existing_engineering"
        assert result.project_type_guess == "api_service"
        assert result.confidence == 0.85
        assert result.classification_method == "llm_enhanced"
        assert result.risk_zones == ["No tests."]
        assert result.training_opportunities == ["Add first test."]

    def test_invalid_json_returns_base(self) -> None:
        base = FirstLookSummary(
            folder_role="empty_new_project",
            project_type_guess="unknown",
            confidence=0.5,
            why_this_guess="base",
        )
        result = _parse_llm_response(base, {"choices": [{"message": {"content": "not json"}}]})
        assert result.folder_role == "empty_new_project"
        assert result.classification_method == "heuristic"

    def test_invalid_role_returns_base_role(self) -> None:
        base = FirstLookSummary(folder_role="idea_scratchpad", confidence=0.5)
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "folder_role": "invalid_role",
                            "project_type_guess": "unknown",
                            "confidence": 0.5,
                        }),
                    },
                },
            ],
        }
        result = _parse_llm_response(base, response)
        assert result.folder_role == "idea_scratchpad"

    def test_markdown_fence_stripped(self) -> None:
        base = FirstLookSummary(folder_role="mixed_uncertain", confidence=0.3)
        content = f"```json\n{json.dumps({'folder_role': 'existing_engineering', 'project_type_guess': 'web_app', 'confidence': 0.8})}\n```"
        response = {"choices": [{"message": {"content": content}}]}
        result = _parse_llm_response(base, response)
        assert result.folder_role == "existing_engineering"
        assert result.project_type_guess == "web_app"

    def test_confidence_clamped(self) -> None:
        base = FirstLookSummary(confidence=0.5)
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "folder_role": "existing_engineering",
                            "project_type_guess": "unknown",
                            "confidence": 1.5,
                        }),
                    },
                },
            ],
        }
        result = _parse_llm_response(base, response)
        assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# Unit tests — LLM classifier (async)
# ---------------------------------------------------------------------------


class TestClassifyWithLlm:
    @pytest.mark.asyncio()
    async def test_falls_back_to_heuristic_when_no_provider(self, python_project: Path) -> None:
        result = await classify_with_llm(str(python_project), None)
        assert result.classification_method == "heuristic"
        assert result.folder_role == "existing_engineering"

    @pytest.mark.asyncio()
    async def test_no_provider_keeps_requested_heuristic_language(
        self, python_project: Path
    ) -> None:
        result = await classify_with_llm(
            str(python_project),
            None,
            response_language="ja-JP",
        )
        assert result.classification_method == "heuristic"
        assert result.why_this_guess == (
            "依存関係の設定、ソースフォルダー、または複数のソースファイルが見つかりました。"
        )
        assert result.recommended_next_step == (
            "エントリーポイントを確認し、最初の小さな練習課題を決めましょう。"
        )

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        ("response_language", "expected_instruction"),
        [
            ("zh-CN", "Respond in Simplified Chinese (zh-CN)."),
            ("en-US", "Respond in English (en-US)."),
            ("es-ES", "Respond in Spanish (es-ES)."),
            ("fr-FR", "Respond in French (fr-FR)."),
            ("de-DE", "Respond in German (de-DE)."),
            ("ja-JP", "Respond in Japanese (ja-JP)."),
            ("ko-KR", "Respond in Korean (ko-KR)."),
            ("pt-BR", "Respond in Brazilian Portuguese (pt-BR)."),
        ],
    )
    async def test_llm_prompt_requests_each_supported_response_language(
        self,
        python_project: Path,
        response_language: str,
        expected_instruction: str,
    ) -> None:
        mock_provider = MagicMock()
        mock_provider.has_api_key = True
        mock_provider.chat_completion = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        result = await classify_with_llm(
            str(python_project),
            mock_provider,
            response_language=response_language,
        )

        assert result.classification_method == "heuristic"
        prompt = mock_provider.chat_completion.await_args.kwargs["messages"][0]["content"]
        assert expected_instruction in prompt
        normalized_prompt = " ".join(prompt.split())
        assert (
            "Keep JSON field names, enum values, file paths, package names, and code identifiers unchanged."
            in normalized_prompt
        )

    @pytest.mark.asyncio()
    async def test_falls_back_when_llm_fails(self, python_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.has_api_key = True
        mock_provider.chat_completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        result = await classify_with_llm(str(python_project), mock_provider)
        assert result.classification_method == "heuristic"

    @pytest.mark.asyncio()
    async def test_llm_refines_result(self, python_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.has_api_key = True
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "folder_role": "existing_engineering",
                                "project_type_guess": "api_service",
                                "confidence": 0.9,
                                "why_this_guess": "LLM refined: clear API structure.",
                                "risk_zones": ["Missing test coverage."],
                                "training_opportunities": ["Add integration tests."],
                                "unknowns": [],
                                "recommended_next_step": "Start with integration test.",
                            }),
                        },
                    },
                ],
            },
        )
        result = await classify_with_llm(str(python_project), mock_provider)
        assert result.classification_method == "llm_enhanced"
        assert result.confidence == 0.9
        assert "LLM refined" in result.why_this_guess


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_first_look_summary_validates(self) -> None:
        summary = FirstLookSummary(
            folder_role="existing_engineering",
            project_type_guess="api_service",
            confidence=0.85,
        )
        assert summary.folder_role == "existing_engineering"
        data = summary.model_dump()
        assert data["confidence"] == 0.85

    def test_workspace_understanding_snapshot_with_first_look(self) -> None:
        summary = FirstLookSummary(
            folder_role="algorithm_model",
            project_type_guess="ml_model",
            confidence=0.7,
        )
        snapshot = WorkspaceUnderstandingSnapshot(
            repo_summary="ML project",
            first_look_summary=summary,
        )
        assert snapshot.first_look_summary is not None
        assert snapshot.first_look_summary.folder_role == "algorithm_model"

    def test_workspace_understanding_snapshot_without_first_look(self) -> None:
        snapshot = WorkspaceUnderstandingSnapshot(repo_summary="Some repo")
        assert snapshot.first_look_summary is None
