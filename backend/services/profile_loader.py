"""
Service for loading and validating the base profile from YAML.
"""
import yaml
from pathlib import Path

from models.profile import Profile


def load_profile(profile_path) -> Profile:
    """
    Load and validate a profile from the YAML file the caller names.

    This is *not* how a profile is chosen: candidate identity is resolved through
    :class:`~services.profile_store.ProfileStore` with an explicit ``profile_id``,
    which fails closed (ADR 0003). There is deliberately no implicit default location;
    the old ``storage/profile/profile.yaml`` is never read. Prefer
    ``Config.load_profile()``.

    Args:
        profile_path: Path to a profile.yaml (required).

    Returns:
        Validated Profile object

    Raises:
        ValueError: If no path is given or profile validation fails
        FileNotFoundError: If profile file doesn't exist
    """
    if profile_path is None or str(profile_path).strip() == "":
        raise ValueError(
            "load_profile() needs an explicit profile path. Resolve a profile through "
            "the store with a profile_id (ADR 0003); there is no implicit default."
        )
    profile_path = Path(profile_path)

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found at: {profile_path}")
    
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        profile = Profile(**data)
        return profile
        
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in profile: {e}")
    except Exception as e:
        raise ValueError(f"Profile validation failed: {e}")
