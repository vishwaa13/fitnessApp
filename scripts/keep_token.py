"""Get a Google Keep master token (Keep has no official API for personal accounts).

1. In a private browser window open https://accounts.google.com/EmbeddedSetup
   and sign in with the Google account that owns your "gym logs" note.
2. When it shows "I agree", open developer tools -> Application/Storage ->
   Cookies -> accounts.google.com and copy the value of the `oauth_token`
   cookie (starts with "oauth2_4/"). It is single-use and expires in minutes.
3. Run:  pip install gkeepapi==0.17.1 && python scripts/keep_token.py

Save the printed token as the GOOGLE_KEEP_MASTER_TOKEN secret and your
address as GOOGLE_EMAIL. The token can read your whole Google account, so
keep it only in GitHub secrets. Revoke it any time at
https://myaccount.google.com/permissions or by changing your password.
"""

import secrets
from getpass import getpass

import gpsoauth


def main() -> None:
    email = input("Google email: ").strip()
    oauth_token = getpass("oauth_token cookie value (not shown): ").strip()
    android_id = secrets.token_hex(8)
    result = gpsoauth.exchange_token(email, oauth_token, android_id)
    token = result.get("Token")
    if not token:
        raise SystemExit(f"Google refused the exchange: {result.get('Error', result)}. "
                         "Get a fresh oauth_token cookie and run this again within a few minutes.")
    print("\nGOOGLE_KEEP_MASTER_TOKEN:\n")
    print(token)


if __name__ == "__main__":
    main()
