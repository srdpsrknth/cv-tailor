"""
Service for loading and validating the base profile from YAML.
"""
import yaml
from pathlib import Path
from typing import Optional

from models.profile import Profile


def load_profile(profile_path: Optional[str] = None) -> Profile:
    """
    Load and validate profile from YAML file.
    
    Args:
        profile_path: Path to profile.yaml (defaults to storage/profile/profile.yaml)
        
    Returns:
        Validated Profile object
        
    Raises:
        FileNotFoundError: If profile file doesn't exist
        ValueError: If profile validation fails
    """
    if profile_path is None:
        # Default path relative to backend/services/
        profile_path = Path(__file__).parent.parent.parent / "storage" / "profile" / "profile.yaml"
    else:
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
