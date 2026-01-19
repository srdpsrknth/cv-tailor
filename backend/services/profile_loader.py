# backend/services/profile_loader.py

from pathlib import Path
import yaml

from backend.models.profile import Profile


DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "storage"
    / "profile"
    / "profile.yaml"
)


def load_profile(profile_path: Path | None = None) -> Profile:
    """
    Load and validate storage/profile/profile.yaml
    """
    path = profile_path or DEFAULT_PROFILE_PATH

    if not path.exists():
        raise FileNotFoundError(f"Profile YAML not found at: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    return Profile.model_validate(data)
