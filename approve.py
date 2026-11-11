#!/usr/bin/env python3
"""Approve a pairing code, list pending codes, or manage the allowlist.
  python3 approve.py <CODE>      approve a pending code
  python3 approve.py --list      show allowlist and pending codes
  python3 approve.py --add <id>  allowlist a numeric Telegram user id
  python3 approve.py --remove <id>
"""
import os, sys
import relay
from relay import approve_code, state

def main(a):
    relay.load_dotenv()          # picks up GROKBOT_DATA_DIR from .env, if set
    relay.configure_paths()
    os.makedirs(relay.HOME, exist_ok=True)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 1
    if a[0] == "--list":
        with state(write=False) as s:
            print("allowlist:", s["allowlist"])
            for c, p in s["pending"].items():
                print(f"pending {c}: user_id={p['user_id']} username={p.get('username')} name={p.get('first_name')}")
        return 0
    if a[0] in ("--add", "--remove") and len(a) == 2:
        uid = int(a[1])
        with state() as s:
            if a[0] == "--add" and uid not in s["allowlist"]:
                s["allowlist"].append(uid)
            if a[0] == "--remove" and uid in s["allowlist"]:
                s["allowlist"].remove(uid)
            print("allowlist:", s["allowlist"])
        return 0
    p = approve_code(a[0])
    if not p:
        print("Unknown or expired code."); return 1
    print(f"Approved user_id={p['user_id']} username={p.get('username')} name={p.get('first_name')}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
