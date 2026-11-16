import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "production" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


visual = load_module("visual_engine_phase3", "automated_visual_engine_v1.py")
gate = load_module("originality_gate_phase3", "premium_originality_gate_v1_3.py")


def test_visual_topic_id_validation_rejects_traversal():
    with pytest.raises(ValueError):
        visual.validate_topic_id("../other-topic")
    with pytest.raises(ValueError):
        visual.validate_topic_id("C:\\temp")


def test_visual_topic_id_validation_accepts_normal_ids():
    visual.validate_topic_id("topic_2026-11")


def test_scene_collection_uses_scene_directions_and_formats():
    creative = {
        "long_video": {
            "scenes": [{
                "scene_id": "01", "section": "Psychology",
                "visual_direction": "A human brain made of light",
                "narration_excerpt": "How memory works",
                "claim_ids": ["C01"],
            }],
            "thumbnail_concepts": [{"concept": "Money trap", "composition": "A broken coin"}],
        },
        "short_video": {
            "scenes": [{
                "scene_id": "S01", "section": "Habits",
                "visual_direction": "A clock in a dark room",
                "narration_excerpt": "Build better habits",
                "claim_ids": [],
            }]
        },
    }
    tasks = visual.collect_tasks(creative)
    assert len(tasks) == 3
    assert tasks[0]["visual_direction"] == "A human brain made of light"
    assert (tasks[0]["width"], tasks[0]["height"]) == (1920, 1080)
    assert (tasks[1]["width"], tasks[1]["height"]) == (1080, 1920)


def test_local_procedural_provenance_is_supported():
    asset = {
        "provenance": {
            "source_type": "local_procedural_original",
            "creator": "Project-authored local visual renderer",
            "source_code_reference": "production/automated_visual_engine_v1.py",
            "rights_basis": "Project-authored Pillow primitives",
            "external_images_used": False,
            "commercial_use_confirmed": True,
        }
    }
    failures, holds = gate.validate_provenance(asset)
    assert failures == []
    assert holds == []


def test_unknown_provenance_is_held():
    failures, holds = gate.validate_provenance({"provenance": {"source_type": "unknown"}})
    assert failures == []
    assert "UNKNOWN_OR_UNDECLARED_SOURCE_TYPE" in holds


def test_approval_flags_remain_false_in_phase2_source():
    source = (ROOT / "production" / "phase2_pipeline_v1.py").read_text(encoding="utf-8")
    assert 'report["production_approved"] = False' in source
    assert 'report["render_authorized"] = False' in source
    assert 'report["upload_authorized"] = False' in source


def test_scene_aware_renderer_creates_valid_image(tmp_path):
    from PIL import Image
    task = {
        "asset_id": "LONG_01", "visual_direction": "A human brain and memory network",
        "narration_excerpt": "Psychology of decisions", "section": "Psychology",
        "width": 640, "height": 360,
    }
    output = tmp_path / "scene.jpg"
    visual.make_artwork(task, output, attempt=0)
    with Image.open(output) as image:
        assert image.size == (640, 360)
        image.verify()


def test_phase2_wires_visual_stages_after_script_gate():
    source = (ROOT / "production" / "phase2_pipeline_v1.py").read_text(encoding="utf-8")
    assert '("automated_fact_check"' in source
    assert '("script_qa"' in source
    assert 'visual_generation' in source
    assert 'visual_originality_gate' in source
    assert source.index('visual_generation') > source.index('evaluate_reports')
