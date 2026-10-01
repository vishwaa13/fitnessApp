"""Log in to Garmin once on your own computer and print tokens for GitHub.

    pip install garminconnect==0.3.2
    python scripts/garmin_login.py

Paste the printed line into a repository secret named GARMIN_TOKENS. GitHub
Actions then never has to log in with your password (and never hits MFA).
"""

from getpass import getpass

from garminconnect import Garmin


def main() -> None:
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password (not shown): ")
    api = Garmin(email, password, prompt_mfa=lambda: input("MFA code from Garmin: ").strip())
    api.login()
    print(f"\nLogged in as {api.full_name or api.display_name}.")
    print("Copy everything on the next line into the GARMIN_TOKENS secret:\n")
    print(api.client.dumps())


if __name__ == "__main__":
    main()
