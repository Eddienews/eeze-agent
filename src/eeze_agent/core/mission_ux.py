"""Mission UX helpers: ready-made recipes, plain-language plan summaries, result files.

Nothing here runs anything. Recipes only pre-fill the Missions form; the plan is still
drafted, shown, validated and approved exactly as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
MODEL_EXTS = {".glb", ".gltf", ".blend"}

# ---------------------------------------------------------------- recipes

RECIPES: list[dict[str, Any]] = [
    {
        "id": "reels-vertical",
        "title": "Vertical video for Reels / Shorts",
        "kind": "video",
        "needs_sources": True,
        "name": "Vertical cut",
        "goal": "Take the clips in the folder in order, trim each to its best 4 seconds, make "
                "each one fill a 1080x1920 vertical frame (fit='fill': crop the sides, no black "
                "bars, no stretching), 30 fps, and join them into one vertical MP4. Also save a "
                "thumbnail at 1 second.",
        "blurb": "Clips → full-screen 9:16 MP4 + thumbnail",
    },
    {
        "id": "photo-slideshow",
        "title": "Slideshow from photos",
        "kind": "video",
        "needs_sources": True,
        "name": "Photo slideshow",
        "goal": "Turn every photo in the folder into a 3-second shot at 1920x1080, 30 fps, "
                "and join them in name order into one MP4.",
        "blurb": "Photos → 1080p MP4, 3 s each",
    },
    {
        "id": "trim-teaser",
        "title": "Short teaser from a long clip",
        "kind": "video",
        "needs_sources": True,
        "name": "Teaser",
        "goal": "From the first clip, keep seconds 2 to 10, scale to 1280x720 at 30 fps and "
                "save it as teaser.mp4 with a thumbnail at 1 second.",
        "blurb": "8-second 720p teaser",
    },
    {
        "id": "rename-sequence",
        "title": "Rename photos in sequence",
        "kind": "files",
        "needs_sources": True,
        "name": "Rename in sequence",
        "goal": "Rename the photos in this folder to park001, park002, park003… in the order "
                "they were taken. Keep the extensions.",
        "blurb": "img001… → park001… · preview + undo",
    },
    {
        "id": "organize-by-month",
        "title": "Organize photos by month",
        "kind": "files",
        "needs_sources": True,
        "name": "Organize by month",
        "goal": "Move the photos in this folder into one sub-folder per month (2026-09, "
                "2026-10…), using the date each photo was taken.",
        "blurb": "Sub-folders per month · undo anytime",
    },
    {
        "id": "find-duplicates",
        "title": "Find duplicate photos",
        "kind": "files",
        "needs_sources": True,
        "name": "Find duplicates",
        "goal": "Find photos in this folder that are exact duplicates of each other. Do not "
                "delete anything, just list them.",
        "blurb": "Lists identical files · deletes nothing",
    },
    {
        "id": "logo-turntable",
        "title": "3D turntable of your name",
        "kind": "3d",
        "needs_sources": False,
        "name": "Name turntable",
        "goal": "Extruded 3D text of the word 'eeze' on a dark glossy floor, a thin cyan ring "
                "above it, one warm key light, camera orbiting once; 4 seconds at 24 fps, "
                "640x640. Save a still, the animation, the .blend and a .glb.",
        "blurb": "Spinning 3D text, MP4 + GLB",
    },
    {
        "id": "product-shot",
        "title": "Simple product hero shot",
        "kind": "3d",
        "needs_sources": False,
        "name": "Product shot",
        "goal": "A glossy orange sphere resting on a white studio floor with a soft area light "
                "and a rim light; a single 1280x720 still from a low three-quarter angle.",
        "blurb": "One clean studio still",
    },
]


_RECIPES_PT: dict[str, tuple[str, str, str, str]] = {
    "reels-vertical": (
        "Vídeo vertical para Reels / Shorts",
        "Corte vertical",
        "Pegue os clipes da pasta em ordem, corte os melhores 4 segundos de cada, faça cada um preencher a tela vertical 1080x1920 (fit='fill': corta as laterais, sem faixas pretas e sem esticar), 30 fps, e junte tudo em um MP4 vertical. Salve também uma miniatura em 1 segundo.",
        "Clipes → MP4 9:16 em tela cheia + miniatura"
    ),
    "photo-slideshow": (
        "Slideshow com fotos",
        "Slideshow",
        "Transforme cada foto da pasta em uma cena de 3 segundos em 1920x1080, 30 fps, e junte todas pela ordem do nome em um MP4.",
        "Fotos → MP4 1080p, 3 s cada"
    ),
    "trim-teaser": (
        "Teaser curto de um vídeo longo",
        "Teaser",
        "Do primeiro clipe, mantenha do segundo 2 ao 10, redimensione para 1280x720 a 30 fps e salve como teaser.mp4 com uma miniatura em 1 segundo.",
        "Teaser 720p de 8 segundos"
    ),
    "rename-sequence": (
        "Renomear fotos em sequência",
        "Renomear em sequência",
        "Renomeie as fotos desta pasta para park001, park002, park003… na ordem em que foram tiradas. Mantenha as extensões.",
        "img001… → park001… · prévia + desfazer"
    ),
    "organize-by-month": (
        "Organizar fotos por mês",
        "Organizar por mês",
        "Mova as fotos desta pasta para uma subpasta por mês (2026-09, 2026-10…), usando a data em que cada foto foi tirada.",
        "Subpastas por mês · desfazer quando quiser"
    ),
    "find-duplicates": (
        "Achar fotos duplicadas",
        "Achar duplicadas",
        "Encontre as fotos desta pasta que são cópias exatas umas das outras. Não apague nada, só liste.",
        "Lista arquivos idênticos · não apaga nada"
    ),
    "logo-turntable": (
        "Seu nome girando em 3D",
        "Nome em 3D",
        "Texto 3D extrudado com a palavra 'eeze' sobre um piso escuro brilhante, um anel ciano fino acima, uma luz principal quente e a câmera dando uma volta; 4 segundos a 24 fps, 640x640. Salve uma imagem, a animação, o .blend e um .glb.",
        "Texto 3D girando, MP4 + GLB"
    ),
    "product-shot": (
        "Foto de produto simples",
        "Foto de produto",
        "Uma esfera laranja brilhante sobre um piso de estúdio branco, com uma luz de área suave e uma luz de recorte; uma única imagem 1280x720 de um ângulo baixo de três quartos.",
        "Uma imagem limpa de estúdio"
    )
}


def recipes() -> list[dict[str, Any]]:
    # Files first: the everyday, high-volume jobs people actually need help with.
    rank = {"files": 0, "video": 1, "photo": 2, "3d": 3, "task": 4}
    out = []
    for recipe in sorted(RECIPES, key=lambda r: rank.get(r["kind"], 9)):
        item = dict(recipe)
        if recipe["id"] in _RECIPES_PT:
            title, name, goal, blurb = _RECIPES_PT[recipe["id"]]
            item.update(title_pt=title, name_pt=name, goal_pt=goal, blurb_pt=blurb)
        out.append(item)
    return out


# ---------------------------------------------------------------- plan summaries

def _fmt_size(value: Any) -> str:
    try:
        w, h = value
        return f"{int(w)}×{int(h)}"
    except (TypeError, ValueError):
        return str(value)


def _video_line(step: dict, pt: bool) -> str:
    op = step.get("op")
    src = step.get("input") or step.get("source") or ("a etapa anterior" if pt else "the previous step")
    if op == "still_to_video":
        return (f"Transformar a imagem “{step.get('source')}” em um clipe de {step.get('duration')} s "
                f"em {_fmt_size(step.get('size'))}" if pt else
                f"Turn image “{step.get('source')}” into a {step.get('duration')} s clip at "
                f"{_fmt_size(step.get('size'))}")
    if op == "trim":
        end = step.get("end")
        if pt:
            span = (f"{step.get('start')}–{end} s" if end is not None
                    else f"{step.get('duration')} s a partir de {step.get('start')} s")
            return f"Cortar “{src}” para {span}"
        span = (f"{step.get('start')}–{end} s" if end is not None
                else f"{step.get('duration')} s from {step.get('start')} s")
        return f"Trim “{src}” to {span}"
    if op == "scale":
        mode = str(step.get("fit", "fit"))
        how = ({"fill": "preenchendo a tela (corta as laterais)", "stretch": "esticando",
                "fit": "inteiro, com faixas pretas"} if pt else
               {"fill": "filling the frame (sides cropped)", "stretch": "stretched",
                "fit": "whole picture, black bars"}).get(mode, mode)
        return (f"Redimensionar “{src}” para {_fmt_size(step.get('size'))}, {how}" if pt else
                f"Resize “{src}” to {_fmt_size(step.get('size'))}, {how}")
    if op == "fps":
        return (f"Colocar “{src}” em {step.get('fps')} fps" if pt else
                f"Set “{src}” to {step.get('fps')} fps")
    if op == "concat":
        joined = ", ".join(f"“{i}”" for i in step.get("inputs") or [])
        return f"Juntar {joined} nesta ordem" if pt else f"Join {joined} in order"
    if op == "thumbnail":
        return (f"Salvar uma miniatura de “{src}” em {step.get('at')} s" if pt else
                f"Save a thumbnail of “{src}” at {step.get('at')} s")
    return f"{op} “{src}”"


def _photo_line(step: dict, pt: bool) -> str:
    op = step.get("op")
    if op == "crop":
        return (f"Recortar uma área de {step.get('width')}×{step.get('height')} a partir de "
                f"({step.get('x')}, {step.get('y')})" if pt else
                f"Crop a {step.get('width')}×{step.get('height')} area starting at "
                f"({step.get('x')}, {step.get('y')})")
    if op == "resize":
        return (f"Redimensionar para {step.get('width')}×{step.get('height')}" if pt else
                f"Resize to {step.get('width')}×{step.get('height')}")
    if op == "adjust":
        parts = []
        b = float(step.get("brightness", 0) or 0)
        c = float(step.get("contrast", 1) if step.get("contrast") is not None else 1)
        s = float(step.get("saturation", 1) if step.get("saturation") is not None else 1)
        if b:
            parts.append(f"{'brilho' if pt else 'brightness'} {'+' if b > 0 else ''}{b:g}")
        if c != 1:
            parts.append(f"{'contraste' if pt else 'contrast'} ×{c:g}")
        if s != 1:
            parts.append(f"{'saturação' if pt else 'saturation'} ×{s:g}")
        if pt:
            return "Ajustar " + (", ".join(parts) if parts else "cores (sem mudança)")
        return "Adjust " + (", ".join(parts) if parts else "colors (no change)")
    if op == "twilight":
        a = int(float(step.get("fade_start", 0)) * 100)
        z = int(float(step.get("fade_end", 1)) * 100)
        return (f"Tom de crepúsculo (força {step.get('strength')}) de {a}% a {z}% da altura — "
                "afeta tudo nessa faixa, não só o céu" if pt else
                f"Twilight tint (strength {step.get('strength')}) fading from {a}% to {z}% of the "
                "height — affects everything in that band, not only the sky")
    return str(op)


_3D_OPS = {
    "render_still": ("Render a still image", "Renderizar uma imagem"),
    "render_animation": ("Render the animation (MP4)", "Renderizar a animação (MP4)"),
    "save_blend": ("Save the Blender scene (.blend)", "Salvar a cena do Blender (.blend)"),
    "export_glb": ("Export a 3D model (.glb)", "Exportar um modelo 3D (.glb)"),
}


def describe_plan(kind: str, plan_text: str, lang: str = "en") -> list[str]:
    """Plain-language lines for a plan (en/pt). Best effort: never raises, [] when unreadable."""
    pt = str(lang).lower().startswith("pt")
    try:
        data = yaml.safe_load(plan_text or "") or {}
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    lines: list[str] = []
    try:
        steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
        if kind == "video":
            srcs = data.get("sources") or {}
            if srcs:
                listed = ", ".join(list(srcs)[:6])
                lines.append(f"Usa {len(srcs)} arquivo(s): {listed}" if pt else
                             f"Uses {len(srcs)} source file(s): {listed}")
            lines += [_video_line(s, pt) for s in steps]
        elif kind == "photo":
            if data.get("source"):
                lines.append(f"Edita “{data.get('source')}” (o original nunca é alterado)" if pt else
                             f"Edits “{data.get('source')}” (the original is never changed)")
            lines += [_photo_line(s, pt) for s in steps]
        elif kind == "3d":
            scene = data.get("scene") or {}
            objects = [o for o in scene.get("objects") or [] if isinstance(o, dict)]
            if objects:
                names = [f"{o.get('kind')}" + (f" “{o.get('text')}”" if o.get("text") else "")
                         for o in objects]
                lines.append(("Cena: " if pt else "Scene: ") + ", ".join(names))
            render = data.get("render") or {}
            if render:
                frames, fps = render.get("frames"), render.get("fps")
                secs = f", {float(frames) / float(fps):.1f} s" if frames and fps else ""
                lines.append(f"{'Renderizar' if pt else 'Render'} {_fmt_size(render.get('resolution'))}"
                             f"{secs} ({render.get('engine', 'EEVEE')})")
            lines += [_3D_OPS.get(str(s.get("op")), (str(s.get("op")),) * 2)[1 if pt else 0]
                      for s in steps]
        elif kind == "task":
            lines += [f"{s.get('action')}: {s.get('intent') or s.get('id')}" for s in steps]
        elif kind == "files":
            lines += _files_lines(data, pt)
        if data.get("output") and kind != "files":
            lines.append(f"{'Arquivo final' if pt else 'Final file'}: {data.get('output')}")
    except Exception:  # noqa: BLE001 — a summary is a convenience, never an error
        return lines
    return lines


def _files_lines(data: dict, pt: bool = False) -> list[str]:
    include = data.get("include", "images")
    if isinstance(include, str):
        what = ({"images": "fotos", "videos": "vídeos", "all": "arquivos"} if pt else
                {"images": "photos", "videos": "videos", "all": "files"}).get(include, include)
    else:
        what = ", ".join(include)
    folder = data.get("folder")
    op = data.get("op")
    if op == "rename":
        if pt:
            order = {"taken": "pela data em que cada foto foi tirada",
                     "modified": "pela data do arquivo"}.get(str(data.get("order")), "pelo nome (ordem natural)")
            return [f"Renomear as {what} em {folder}",
                    f"Novos nomes: {data.get('pattern')} (contador começa em {data.get('start', 1)}), "
                    f"ordenados {order}; extensões mantidas",
                    "Você vê cada nome antigo → novo antes de qualquer mudança, e pode desfazer"]
        order = {"taken": "the date each photo was taken", "modified": "file date"}.get(
            str(data.get("order")), "name (natural order)")
        return [f"Rename the {what} in {folder}",
                f"New names: {data.get('pattern')} (counter starts at {data.get('start', 1)}), "
                f"sorted by {order}; extensions kept",
                "You see every old → new name before anything changes, and can undo"]
    if op == "organize":
        by = str(data.get("by", "month"))
        if pt:
            by_pt = {"month": "mês", "day": "dia", "year": "ano", "type": "tipo"}.get(by, by)
            return [f"Mover as {what} de {folder} para subpastas por {by_pt}",
                    "Nada é apagado; desfazer devolve cada arquivo ao lugar"]
        return [f"Move the {what} in {folder} into sub-folders by {by}",
                "Nothing is deleted; undo puts every file back"]
    if op == "duplicates":
        if pt:
            return [f"Achar {what} idênticas em {folder} (pelo conteúdo, não só pelo nome)",
                    "Só lista — nada é apagado"]
        return [f"Find identical {what} in {folder} (content, not just name)",
                "Only lists them — nothing is deleted"]
    return []


# ---------------------------------------------------------------- result files

def _kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in MODEL_EXTS:
        return "model"
    return "other"


def output_files(repo_root: Path, out_dir: str | None, limit: int = 40) -> list[dict]:
    """Deliverables of a mission run, as URLs under the /artifacts mount."""
    if not out_dir:
        return []
    artifacts = (Path(repo_root) / "artifacts").resolve()
    root = Path(out_dir).resolve()
    if not root.is_dir() or not root.is_relative_to(artifacts):
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _kind_of(path) == "other":
            continue
        rel = path.relative_to(artifacts).as_posix()
        # Files under a "work" folder are intermediate steps (crop, resize…), not deliverables.
        step = "work" in path.relative_to(root).parts[:-1]
        files.append({"name": path.name, "kind": _kind_of(path), "size": path.stat().st_size,
                      "url": "/artifacts/" + quote(rel), "step": step})
        if len(files) >= limit:
            break
    # Deliverables first (video, image), then models.
    order = {"video": 0, "image": 1, "model": 2}
    return sorted(files, key=lambda f: (f["step"], order.get(f["kind"], 3), f["name"]))


def source_files(sources: str, limit: int = 24) -> list[dict]:
    """Image/video files directly inside a mission's sources folder (or the one file named)."""
    from eeze_agent.brains.specwriter import split_sources

    if not str(sources or "").strip():
        return []
    folder, only = split_sources(sources)
    if not folder.is_dir():
        return []
    out = []
    for path in [only] if only is not None else sorted(folder.iterdir()):
        if path.is_file() and _kind_of(path) in {"image", "video"}:
            out.append({"name": path.name, "kind": _kind_of(path), "size": path.stat().st_size})
            if len(out) >= limit:
                break
    return out


def resolve_source_file(sources: str, name: str) -> Path | None:
    """The file ``name`` inside the sources folder — no traversal, media types only."""
    from eeze_agent.brains.specwriter import split_sources

    if not str(sources or "").strip() or not name:
        return None
    folder, only = split_sources(sources)
    if not folder.is_dir() or (only is not None and only.name != name):
        return None
    if "/" in name or "\\" in name or name in {".", ".."}:
        return None
    candidate = (folder / name).resolve()
    if candidate.parent != folder.resolve() or not candidate.is_file():
        return None
    if _kind_of(candidate) not in {"image", "video"}:
        return None
    return candidate
