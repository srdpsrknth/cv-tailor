"""
Validation script for profile.yaml
Run this to ensure your profile YAML is correctly formatted.
"""
import yaml
import sys
from pathlib import Path
from pydantic import ValidationError

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from models.profile import Profile


def validate_profile(profile_path: str = "../storage/profile/profile.yaml") -> bool:
    """
    Validate profile YAML file against Pydantic model.
    
    Args:
        profile_path: Path to profile.yaml file
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Load YAML
        yaml_path = Path(__file__).parent / profile_path
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # Validate against model
        profile = Profile(**data)
        
        # Success - print summary
        print("=" * 60)
        print("SUCCESS: Profile YAML is valid!")
        print("=" * 60)
        print(f"\nProfile: {profile.identity.full_name}")
        print(f"Email: {profile.identity.email}")
        print(f"Location: {profile.identity.location}")
        print(f"\nContent Summary:")
        print(f"  - Professional experiences: {len(profile.experience)}")
        print(f"  - Education entries: {len(profile.education)}")
        print(f"  - Certifications: {len(profile.certifications)}")
        print(f"  - Skill categories: {len(profile.skills)}")
        print(f"  - Languages: {len(profile.languages)}")
        
        print(f"\nSkill Categories:")
        for category, skills in profile.skills.items():
            print(f"  - {category}: {len(skills)} skills")
        
        print(f"\nExperiences (reverse chronological):")
        for exp in profile.experience:
            print(f"  - {exp.company} ({exp.role}): {exp.start_date} to {exp.end_date}")
            print(f"    Bullets: {len(exp.bullets)}, Projects: {len(exp.selected_projects)}, Tech: {len(exp.technologies)}")
        
        print("\n" + "=" * 60)
        print("Validation complete. Profile is ready to use.")
        print("=" * 60)
        return True
        
    except FileNotFoundError:
        print(f"ERROR: Profile file not found at {yaml_path}")
        return False
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML syntax")
        print(str(e))
        return False
    except ValidationError as e:
        print(f"ERROR: Profile validation failed")
        print("\nValidation errors:")
        for error in e.errors():
            loc = " -> ".join(str(l) for l in error['loc'])
            print(f"  [{loc}] {error['msg']}")
            print(f"    Input: {error.get('input', 'N/A')}")
        return False
    except Exception as e:
        print(f"ERROR: Unexpected error during validation")
        print(str(e))
        return False


if __name__ == "__main__":
    success = validate_profile()
    sys.exit(0 if success else 1)
