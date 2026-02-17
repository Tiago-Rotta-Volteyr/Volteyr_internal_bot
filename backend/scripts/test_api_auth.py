#!/usr/bin/env python3
"""
Test that API auth works (Supabase JWT → GET /api/auth/me, optional POST /api/chat).

Usage:
  cd backend
  python scripts/test_api_auth.py
  python scripts/test_api_auth.py your@email.com yourpassword
  python scripts/test_api_auth.py --token "eyJ..."   # use an existing access token

Requires: .env with SUPABASE_URL, SUPABASE_KEY. For sign-in: a user in Supabase Auth.
Backend must be running: uvicorn app.main:app --reload (default http://127.0.0.1:8000).
"""
import os
import sys
from pathlib import Path

# Load backend .env
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")


def get_token_from_supabase(email: str, password: str) -> str:
    """Get access token via Supabase Auth REST API (no supabase-py dependency)."""
    import httpx
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        sys.exit(1)
    r = httpx.post(
        f"{url}/auth/v1/token?grant_type=password",
        headers={"apikey": key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        msg = err.get("error_description") or err.get("msg") or r.text or "Sign-in failed"
        print(f"ERROR: {msg}")
        sys.exit(1)
    data = r.json()
    token = data.get("access_token")
    if not token:
        print("ERROR: No access_token in response")
        sys.exit(1)
    return token


def main():
    token = None
    if len(sys.argv) >= 2 and sys.argv[1] == "--token" and len(sys.argv) >= 3:
        token = sys.argv[2]
    elif len(sys.argv) >= 3:
        email, password = sys.argv[1], sys.argv[2]
        print("Signing in with Supabase...")
        token = get_token_from_supabase(email, password)
        print("Got access token.")
    else:
        email = os.getenv("TEST_USER_EMAIL")
        password = os.getenv("TEST_USER_PASSWORD")
        if email and password:
            print("Signing in with TEST_USER_EMAIL...")
            token = get_token_from_supabase(email, password)
            print("Got access token.")
        else:
            print("Usage:")
            print("  python scripts/test_api_auth.py your@email.com yourpassword")
            print("  python scripts/test_api_auth.py --token <access_token>")
            print("  Or set TEST_USER_EMAIL and TEST_USER_PASSWORD in .env")
            sys.exit(1)

    import httpx

    headers = {"Authorization": f"Bearer {token}"}

    # 1) GET /api/auth/me
    print(f"\n1) GET {BASE_URL}/api/auth/me")
    r = httpx.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"   FAIL: {r.status_code} - {r.text}")
        sys.exit(1)
    print(f"   OK: {r.json()}")
    user_id = r.json().get("id")
    print(f"   → User id: {user_id}, email: {r.json().get('email')}")

    # 2) POST /api/chat (minimal message, just check 200 and stream starts)
    print(f"\n2) POST {BASE_URL}/api/chat (streaming)")
    with httpx.stream(
        "POST",
        f"{BASE_URL}/api/chat",
        headers={**headers, "Accept": "text/event-stream"},
        json={"messages": [{"role": "user", "content": "Dis juste OK."}]},
        timeout=30,
    ) as r:
        if r.status_code != 200:
            body = r.read().decode(errors="replace")
            print(f"   FAIL: {r.status_code} - {body[:500]}")
            sys.exit(1)
        # Read first chunk to confirm stream
        for chunk in r.iter_bytes():
            if chunk:
                print(f"   OK: stream started (first chunk: {chunk[:80]!r}...)")
                break

    print("\n✅ Auth and chat API are working.")


if __name__ == "__main__":
    main()
