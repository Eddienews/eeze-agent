"""Declarative 3D scene spec for the render3d vertical + strict YAML loader.

The spec is the contract between a brain (which will write it — C3) and Blender (which
executes it): primitives + transforms + materials, one camera (optionally orbiting), the
lights, render settings, and the ordered steps that produce artifacts. Validation is
strict so the generated Blender script never has to guess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ObjectKind = Literal["cube", "sphere", "torus", "cylinder", "cone", "plane", "text"]
Op3D = Literal["save_blend", "render_still", "render_animation", "export_glb"]
Engine = Literal["BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"]

Vec3 = tuple[float, float, float]
Rgb = tuple[float, float, float]


class SceneObject(BaseModel):
    kind: ObjectKind
    name: str | None = None
    text: str | None = None  # kind == "text"
    location: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)  # degrees, XYZ
    scale: Vec3 = (1.0, 1.0, 1.0)
    color: Rgb = (0.8, 0.8, 0.8)
    metallic: float = 0.0
    roughness: float = 0.45
    params: dict[str, float] = Field(default_factory=dict)  # per-kind: size/radius/depth/…

    @model_validator(mode="after")
    def _check(self) -> SceneObject:
        # Numeric fields are already pydantic-validated (tuple[float, ...] / float);
        # no hand-rolled isinstance pass here — it could never fire and ruff flags the
        # exception type such a check would need.
        if self.kind == "text" and not self.text:
            raise ValueError("kind 'text' requires `text`")
        return self


class Orbit(BaseModel):
    revolutions: float = 1.0
    radius: float | None = None  # distance from look_at; derived from location when None
    height: float | None = None  # camera height relative to look_at; derived when None

    @model_validator(mode="after")
    def _check(self) -> Orbit:
        if self.revolutions <= 0:
            raise ValueError("orbit.revolutions must be > 0")
        return self


class Camera(BaseModel):
    location: Vec3 = (5.5, -5.5, 3.5)
    look_at: Vec3 = (0.0, 0.0, 0.0)
    lens: float = 50.0
    orbit: Orbit | None = None  # when set, the camera orbits look_at across the animation

    @model_validator(mode="after")
    def _check(self) -> Camera:
        if self.lens <= 0:
            raise ValueError("camera.lens must be > 0")
        return self


class Light(BaseModel):
    kind: Literal["sun", "area", "point"] = "sun"
    location: Vec3 = (4.0, -4.0, 6.0)
    energy: float = 4.0
    color: Rgb = (1.0, 1.0, 1.0)
    size: float = 3.0  # area lights only

    @model_validator(mode="after")
    def _check(self) -> Light:
        if self.energy <= 0:
            raise ValueError("light.energy must be > 0")
        return self


class RenderSpec(BaseModel):
    engine: Engine = "BLENDER_EEVEE"
    resolution: tuple[int, int] = (480, 480)
    fps: float = 12.0
    frames: int = 24
    samples: int | None = None  # EEVEE taa_render_samples / Cycles samples
    film_transparent: bool = False
    background: Rgb = (0.015, 0.015, 0.02)

    @model_validator(mode="after")
    def _check(self) -> RenderSpec:
        w, h = self.resolution
        if w <= 0 or h <= 0:
            raise ValueError("resolution must be positive")
        if w % 2 or h % 2:
            raise ValueError("resolution must be even (h264)")
        if self.fps <= 0:
            raise ValueError("fps must be > 0")
        if self.frames < 1:
            raise ValueError("frames must be >= 1")
        if self.samples is not None and self.samples < 1:
            raise ValueError("samples must be >= 1")
        return self


class Scene(BaseModel):
    objects: list[SceneObject]
    camera: Camera = Field(default_factory=Camera)
    lights: list[Light] = Field(default_factory=lambda: [Light()])

    @model_validator(mode="after")
    def _check(self) -> Scene:
        if not self.objects:
            raise ValueError("scene.objects must have at least one object")
        if not self.lights:
            raise ValueError("scene.lights must have at least one light")
        return self


class Step3D(BaseModel):
    id: str
    op: Op3D
    frame: int | None = None  # render_still: 1-based frame (default 1)
    target: str | None = None  # file name inside the run dir; default <id>.<ext>

    @model_validator(mode="after")
    def _check(self) -> Step3D:
        if self.op == "render_still" and self.frame is not None and self.frame < 1:
            raise ValueError("frame must be >= 1")
        if self.target and ("/" in self.target or "\\" in self.target):
            raise ValueError("target must be a plain file name")
        return self


class Scene3DSpec(BaseModel):
    name: str
    description: str = ""
    scene: Scene
    render: RenderSpec = Field(default_factory=RenderSpec)
    steps: list[Step3D]
    output: str | None = None  # final file name, or the id of the step whose artifact is it

    @model_validator(mode="after")
    def _check(self) -> Scene3DSpec:
        if not self.steps:
            raise ValueError("steps must not be empty")
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        return self


def load_spec(path: Path | str) -> Scene3DSpec:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: spec file must contain a YAML mapping")
    return Scene3DSpec(**data)
