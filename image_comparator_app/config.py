import configparser
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SessionState:
    last_folder: Path
    geometry: str = ""
    compare_mode: str = "SIDE_BY_SIDE"
    lens_zoom: float = 4.0
    lens_size: int = 160
    overlay_opacity: float = 0.5


def resolve_app_base_path() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is not None:
        return Path(bundle_dir)
    return Path(__file__).resolve().parent.parent


def load_session_state(config_path: Path) -> SessionState:
    default_dir = resolve_app_base_path()
    parser = configparser.ConfigParser()
    raw = {}

    try:
        if config_path.exists():
            parser.read(config_path, encoding="utf-8")
            raw = dict(parser["app"]) if parser.has_section("app") else {}
    except (configparser.Error, OSError, ValueError):
        raw = {}

    last_folder = _resolve_last_folder(raw.get("last_folder"), default_dir)
    return SessionState(
        last_folder=last_folder,
        geometry=raw.get("geometry", ""),
        compare_mode=raw.get("compare_mode", "SIDE_BY_SIDE"),
        lens_zoom=_safe_float(raw.get("lens_zoom"), 4.0, minimum=1.0, maximum=10.0),
        lens_size=_safe_int(raw.get("lens_size"), 160, minimum=60, maximum=400),
        overlay_opacity=_safe_float(
            raw.get("overlay_opacity"),
            0.5,
            minimum=0.0,
            maximum=1.0,
        ),
    )


def save_session_state(config_path: Path, state: SessionState) -> None:
    parser = configparser.ConfigParser()
    parser["app"] = {
        "last_folder": str(state.last_folder),
        "geometry": state.geometry,
        "compare_mode": state.compare_mode,
        "lens_zoom": f"{state.lens_zoom:.2f}",
        "lens_size": str(state.lens_size),
        "overlay_opacity": f"{state.overlay_opacity:.2f}",
    }
    try:
        with config_path.open("w", encoding="utf-8") as file_obj:
            parser.write(file_obj)
    except OSError:
        pass


def _resolve_last_folder(raw_path: str | None, default_dir: Path) -> Path:
    if not raw_path:
        return default_dir

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (default_dir / candidate).resolve()
    if candidate.exists() and candidate.is_dir():
        return candidate
    return default_dir


def _safe_float(
    raw_value: str | None,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_int(
    raw_value: str | None,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
