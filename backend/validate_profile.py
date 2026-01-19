from backend.services.profile_loader import load_profile

if __name__ == "__main__":
    profile = load_profile()
    print("OK: profile.yaml is valid.")
    print(f"Name: {profile.identity.full_name}")
    print(f"Experiences: {len(profile.experience)}")
    print(f"Education entries: {len(profile.education)}")
