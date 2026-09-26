"""C3 — spec writer: vocabulary locked against the validators, write loop, feasibility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from eeze_agent.brains.specwriter import (
    SpecWriteError,
    SpecWriter,
    _feasibility_photo,
    _feasibility_video,
    collect_sources,
)
from eeze_agent.verticals.photo.spec import PhotoSpec, PhotoStep
from eeze_agent.verticals.photo.vocab import PHOTO_OPS, describe_photo_vocab
from eeze_agent.verticals.render3d.spec import ObjectKind, Op3D, Scene3DSpec, Step3D
from eeze_agent.verticals.render3d.vocab import OBJECT_KINDS, STEP_OPS, describe_3d_vocab
from eeze_agent.verticals.video.spec import OpName, VideoSpec, VideoStep
from eeze_agent.verticals.video.vocab import VIDEO_OPS, describe_video_vocab

# ---------------- vocabulary is the truth ----------------

VIDEO_VALUES = {
    "id": "s1",
    "source": "clip",
    "inputs": ["a", "b"],
    "duration": 1.0,
    "start": 0.0,
    "end": 1.0,
    "size": [480, 480],
    "fps": 25.0,
    "at": 0.0,
}


def _video_step(op: str, fields: list[str]) -> dict:
    payload = {"id": "s1", "op": op}
    payload.update({f: VIDEO_VALUES[f] for f in fields})
    return payload


def test_video_vocab_covers_every_op():
    assert set(VIDEO_OPS) == set(get_args(OpName))


def test_video_vocab_required_fields_are_exactly_required():
    for op, meta in VIDEO_OPS.items():
        minimal = _video_step(op, meta["required"])
        VideoStep(**minimal)  # must construct as-is
        for field_name in meta["required"]:
            broken = dict(minimal)
            broken.pop(field_name)
            with pytest.raises(ValidationError):
                VideoStep(**broken)


def test_trim_accepts_start_plus_end_as_an_alternative():
    # the table lists duration as required, but the validator accepts start+end too —
    # documenting the alternative keeps the table honest.
    VideoStep(id="t", op="trim", start=0.0, end=2.0)


def test_photo_vocab_matches_validator():
    assert set(PHOTO_OPS) == set(get_args(PhotoStep.model_fields["op"].annotation))
    values = {"x": 0, "y": 0, "width": 80, "height": 80,
              "strength": 0.7, "fade_start": 0.2, "fade_end": 0.7}
    for op, meta in PHOTO_OPS.items():
        payload = {"id": "edit", "op": op, **{key: values[key] for key in meta["required"]}}
        PhotoStep(**payload)
        for field in meta["required"]:
            with pytest.raises(ValidationError):
                PhotoStep(**{key: value for key, value in payload.items() if key != field})
    text = describe_photo_vocab()
    assert all(op in text for op in PHOTO_OPS)
    assert "exact" in text.lower() and "png" in text.lower()


def test_3d_vocab_covers_every_kind_and_op():
    assert set(OBJECT_KINDS) == set(get_args(ObjectKind))
    assert set(STEP_OPS) == set(get_args(Op3D))
    for op in STEP_OPS:
        Step3D(id="s", op=op)  # every op is constructible with no extra fields


def test_describe_functions_name_the_ops():
    video = describe_video_vocab()
    assert "concat" in video and "thumbnail" in video and "even" in video
    scene = describe_3d_vocab()
    assert "render_animation" in scene and "torus" in scene and "orbit" in scene


# ---------------- collect_sources ----------------

def test_collect_sources_names_paths_and_ignores_unknown_exts(tmp_path):
    (tmp_path / "Teaser Raw.mp4").write_bytes(b"x" * 16)
    (tmp_path / "mascot.png").write_bytes(b"y" * 16)
    (tmp_path / "notes.txt").write_text("ignore me")
    names, facts = collect_sources(tmp_path)
    assert set(names) == {"teaser-raw", "mascot"}
    assert Path(names["teaser-raw"]).is_absolute()
    assert facts["teaser-raw"]["kind"] == "video" and facts["mascot"]["kind"] == "image"


def test_collect_sources_refuses_an_empty_dir(tmp_path):
    with pytest.raises(SpecWriteError):
        collect_sources(tmp_path)


# ---------------- write loop ----------------

GOOD_VIDEO = json.dumps(
    {
        "name": "goal-edit",
        "sources": {"clip": "C:/x/clip.mp4"},
        "steps": [{"id": "cut", "op": "trim", "input": "clip", "start": 0.0, "duration": 1.0}],
        "output": "out.mp4",
    }
)

BAD_VIDEO = json.dumps(  # still_to_video without size: the validator must refuse it
    {
        "name": "goal-edit",
        "sources": {"clip": "C:/x/clip.mp4"},
        "steps": [{"id": "still", "op": "still_to_video", "source": "still", "duration": 2.0}],
        "output": "out.mp4",
    }
)

GOOD_SCENE = json.dumps(
    {
        "name": "goal-scene",
        "scene": {"objects": [{"kind": "torus", "location": [0, 0, 1]}]},
        "render": {"frames": 24, "fps": 12},
        "steps": [{"id": "anim", "op": "render_animation"}],
        "output": "anim.mp4",
    }
)


class _FakeLLM:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.last = ""

    def __call__(self, system: str, user: str) -> tuple[str, int]:
        self.systems.append(system)
        self.prompts.append(user)
        if self.replies:
            self.last = self.replies.pop(0)
        return self.last, 1111


def test_write_video_valid_first_try(tmp_path):
    fake = _FakeLLM([GOOD_VIDEO])
    writer = SpecWriter(client=fake, model="fake/model")
    result = writer.write_video(
        "cut one second",
        sources={"clip": "C:/x/clip.mp4"},
        facts={"clip": {"kind": "video", "duration_s": 6.0}},
        out_dir=tmp_path,
    )
    assert result.spec.name == "goal-edit" and result.spec.steps[0].op == "trim"
    assert len(result.attempts) == 1 and result.attempts[0]["error"] is None
    assert result.tokens == 1111 and result.cost_usd > 0
    assert result.spec_path.read_text(encoding="utf-8").startswith("name: goal-edit")
    report = json.loads((tmp_path / "write-report.json").read_text(encoding="utf-8"))
    assert report["attempts"][0]["attempt"] == 1 and report["model"] == "fake/model"
    # the prompt carries the vocabulary and the source facts
    assert "SOURCES" in fake.prompts[0] and "duration_s=6.0" in fake.prompts[0]
    assert "concat" in fake.systems[0]


def test_write_video_feeds_the_validation_error_back(tmp_path):
    fake = _FakeLLM([BAD_VIDEO, GOOD_VIDEO])
    writer = SpecWriter(client=fake)
    result = writer.write_video(
        "make a clip",
        sources={"clip": "C:/x/clip.mp4"},
        facts={"clip": {"kind": "video", "duration_s": 6.0}},
        out_dir=tmp_path,
    )
    assert len(result.attempts) == 2
    assert "REJECTED" in fake.prompts[1]
    assert "size" in fake.prompts[1]  # the validator's own words, not a paraphrase
    assert result.spec.steps[0].op == "trim"


def test_write_video_gives_up_loudly(tmp_path):
    fake = _FakeLLM([BAD_VIDEO, BAD_VIDEO, BAD_VIDEO])
    writer = SpecWriter(client=fake, max_attempts=3)
    with pytest.raises(SpecWriteError) as err:
        writer.write_video(
            "make a clip",
            sources={"clip": "C:/x/clip.mp4"},
            facts={"clip": {"kind": "video", "duration_s": 6.0}},
            out_dir=tmp_path,
        )
    assert "3 attempt" in str(err.value)
    report = json.loads((tmp_path / "write-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and len(report["attempts"]) == 3


def test_write_photo_retries_invented_source_and_uses_real_image(tmp_path):
    wrong = json.dumps({
        "name": "avatar", "source": "eeze", "steps": [
            {"id": "crop", "op": "crop", "x": 10, "y": 10, "width": 600, "height": 600},
        ], "output": "avatar.png",
    })
    correct = json.dumps({
        "name": "avatar", "source": "C:/inputs/eeze.png", "steps": [
            {"id": "crop", "op": "crop", "x": 10, "y": 10, "width": 600, "height": 600},
        ], "output": "avatar.png",
    })
    fake = _FakeLLM([wrong, correct])
    result = SpecWriter(client=fake, model="fake/model").write_photo(
        "make a square avatar", sources={"eeze": "C:/inputs/eeze.png"},
        facts={"eeze": {"path": "C:/inputs/eeze.png", "kind": "image",
                        "width": 1254, "height": 1254, "codec_v": "png"}},
        out_dir=tmp_path,
    )
    assert result.kind == "photo" and result.spec.source == "C:/inputs/eeze.png"
    assert len(result.attempts) == 2 and "exact" in result.attempts[0]["error"]
    assert "REJECTED" in fake.prompts[1]
    assert "crop" in fake.systems[0] and "1254" in fake.prompts[0]
    assert (tmp_path / "spec.yaml").is_file()


def test_written_photo_plan_roundtrips_without_invalid_default_fields(tmp_path):
    from eeze_agent.verticals.photo.spec import load_spec

    reply = json.dumps({
        "name": "avatar", "source": "C:/inputs/eeze.png",
        "steps": [
            {"id": "crop-symbol", "op": "crop", "x": 307, "y": 205,
             "width": 640, "height": 640},
            {"id": "resize-avatar", "op": "resize", "width": 600, "height": 600},
            {"id": "adjust-glow", "op": "adjust", "brightness": 0.02,
             "contrast": 1.1, "saturation": 1.12},
        ], "output": "avatar.png",
    })
    result = SpecWriter(client=_FakeLLM([reply]), model="fake/model").write_photo(
        "make a local avatar", sources={"eeze": "C:/inputs/eeze.png"},
        facts={"eeze": {"path": "C:/inputs/eeze.png", "kind": "image",
                        "codec_v": "png", "width": 1254, "height": 1254}},
        out_dir=tmp_path,
    )
    restored = load_spec(result.spec_path)
    assert [step.op for step in restored.steps] == ["crop", "resize", "adjust"]
    text = result.spec_path.read_text(encoding="utf-8")
    assert text.count("brightness:") == 1
    assert text.count("x:") == 1


def test_photo_feasibility_refuses_crop_past_probed_image():
    spec = PhotoSpec(
        name="avatar", source="C:/inputs/eeze.png", output="avatar.png",
        steps=[PhotoStep(id="crop", op="crop", x=1190, y=0, width=100, height=100)],
    )
    facts = {"eeze": {"path": "C:/inputs/eeze.png", "kind": "image",
                       "codec_v": "png", "width": 1254, "height": 1254}}
    assert "outside current" in _feasibility_photo(spec, facts)[0]
    assert "exact path" in _feasibility_photo(
        PhotoSpec(name="x", source="eeze", output="out.png",
                  steps=[PhotoStep(id="size", op="resize", width=60, height=60)]), facts,
    )[0]


# ---------------- feasibility against real facts ----------------

def test_feasibility_refuses_a_trim_past_the_end():
    spec = VideoSpec(
        name="x",
        sources={"clip": "C:/x/clip.mp4"},
        steps=[VideoStep(id="cut", op="trim", input="clip", start=5.0, duration=2.0)],
    )
    problems = _feasibility_video(spec, {"clip": {"kind": "video", "duration_s": 6.0}})
    assert problems and "exceeds" in problems[0]


def test_feasibility_refuses_a_trim_with_nothing_to_cut_from():
    spec = VideoSpec(
        name="x",
        sources={"clip": "C:/x/clip.mp4"},
        steps=[VideoStep(id="cut", op="trim", start=0.0, duration=2.0)],
    )
    problems = _feasibility_video(spec, {"clip": {"kind": "video", "duration_s": 6.0}})
    assert problems and "no previous step" in problems[0]


def test_feasibility_refuses_a_source_path_that_is_not_the_real_path():
    spec = VideoSpec(
        name="x",
        sources={"clip": "clip"},  # the model echoing the NAME instead of the path
        steps=[VideoStep(id="cut", op="trim", input="clip", start=0.0, duration=1.0)],
    )
    facts = {"clip": {"kind": "video", "duration_s": 6.0, "path": "C:/x/clip.mp4"}}
    problems = _feasibility_video(spec, facts)
    assert problems and "exact path" in problems[0]


def test_feasibility_refuses_an_invented_source_name():
    spec = VideoSpec(
        name="x",
        sources={"clip": "C:/x/clip.mp4", "broll": "C:/x/broll.mp4"},
        steps=[VideoStep(id="cut", op="trim", input="clip", start=0.0, duration=1.0)],
    )
    facts = {"clip": {"kind": "video", "duration_s": 6.0, "path": "C:/x/clip.mp4"}}
    problems = _feasibility_video(spec, facts)
    assert problems and "not one of the provided sources" in problems[0]


def test_collect_sources_carries_the_absolute_path(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x" * 8)
    _names, facts = collect_sources(tmp_path)
    assert facts["a"]["path"] == str((tmp_path / "a.mp4").resolve())


def test_feasibility_refuses_a_video_where_a_still_is_needed():
    spec = VideoSpec(
        name="x",
        sources={"clip": "C:/x/clip.mp4"},
        steps=[VideoStep(id="still", op="still_to_video", source="clip", duration=1.0, size=(480, 480))],
    )
    problems = _feasibility_video(spec, {"clip": {"kind": "video", "duration_s": 6.0}})
    assert problems and "still image" in problems[0]


def test_write_video_retries_after_a_feasibility_refusal(tmp_path):
    infeasible = json.dumps(
        {
            "name": "goal-edit",
            "sources": {"clip": "C:/x/clip.mp4"},
            "steps": [{"id": "cut", "op": "trim", "input": "clip", "start": 5.0, "duration": 2.0}],
            "output": "out.mp4",
        }
    )
    fake = _FakeLLM([infeasible, GOOD_VIDEO])
    writer = SpecWriter(client=fake)
    result = writer.write_video(
        "cut the first second",
        sources={"clip": "C:/x/clip.mp4"},
        facts={"clip": {"kind": "video", "duration_s": 6.0}},
        out_dir=tmp_path,
    )
    assert len(result.attempts) == 2
    assert "feasibility" in (result.attempts[0]["error"] or "")


# ---------------- 3d ----------------

def test_write_scene_valid(tmp_path):
    fake = _FakeLLM([GOOD_SCENE])
    writer = SpecWriter(client=fake)
    result = writer.write_scene("a spinning ring", out_dir=tmp_path)
    assert isinstance(result.spec, Scene3DSpec) and result.spec.steps[0].op == "render_animation"
    assert "3D SCENE SPEC" in fake.systems[0]


def test_write_scene_refuses_a_one_frame_animation(tmp_path):
    one_frame = json.dumps(
        {
            "name": "s",
            "scene": {"objects": [{"kind": "cube"}]},
            "render": {"frames": 1},
            "steps": [{"id": "anim", "op": "render_animation"}],
            "output": "a.mp4",
        }
    )
    fake = _FakeLLM([one_frame, GOOD_SCENE])
    writer = SpecWriter(client=fake)
    result = writer.write_scene("move it", out_dir=tmp_path)
    assert len(result.attempts) == 2 and "frames < 2" in (result.attempts[0]["error"] or "")


# ---------------- cli ----------------

def test_cmd_spec_3d_writes_and_reports(tmp_path, monkeypatch, capsys):
    from eeze_agent import cli

    class _Echo(SpecWriter):
        def __init__(self, *a, **kw):
            super().__init__(client=_FakeLLM([GOOD_SCENE]), model="fake/model")

    monkeypatch.setattr("eeze_agent.brains.specwriter.SpecWriter", _Echo)
    args = type(
        "Args",
        (),
        {"kind": "3d", "goal": "a spinning ring", "sources": None, "out": str(tmp_path),
         "run": False, "model": None, "ffmpeg_dir": None, "blender": None},
    )()
    assert cli.cmd_spec(args) == 0
    out = capsys.readouterr().out
    assert "spec written" in out and "fake/model" in out
    assert (tmp_path / "spec.yaml").exists() and (tmp_path / "write-report.json").exists()
