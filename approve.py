#!/usr/bin/env python3
"""Approve a pairing code, list pending codes, or manage users and roles.
  python3 approve.py <CODE>                 approve a pending code as member (default)
  python3 approve.py <CODE> --admin         approve a pending code as admin
  python3 approve.py <CODE> --role admin|member
  python3 approve.py --list                 show users with roles, and pending codes
  python3 approve.py --add <id> [--admin | --role admin|member]   add a numeric Telegram user id
  python3 approve.py --role <id> admin|member                     change an approved user's role
  python3 approve.py --remove <id>

Admins' messages go to the Grok Bot webhook (full agent). Members only get chat replies from a
no-tools LLM call and can never reach the webhook. Only admins can /approve, /promote, /demote.
"""
import sys
import relay
from relay import ROLES, approve_code, remove_user, set_role, state

def _role_flag(a):
    """Pop --admin / --role <r> from a; return role or None."""
    role = None
    if "--admin" in a:
        a.remove("--admin"); role = "admin"
    if "--role" in a:
        i = a.index("--role")
        if i + 1 >= len(a) or a[i + 1] not in ROLES:
            raise SystemExit("--role needs admin or member")
        role = a[i + 1]; del a[i:i + 2]
    return role

def _show(s):
    for u, r in sorted(s["roles"].items(), key=lambda x: (x[1] != "admin", x[0])):
        print(f"user_id={u} role={r}")

def main(a):
    relay.load_dotenv()          # picks up GROKBOT_DATA_DIR from .env, if set
    relay.configure_paths()
    relay.secure_runtime()
    a = list(a)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 1
    if a[0] == "--list":
        with state(write=False) as s:
            _show(s)
            for c, p in s["pending"].items():
                print(f"pending {c}: user_id={p['user_id']} username={p.get('username')} name={p.get('first_name')}")
        return 0
    if a[0] == "--role" and len(a) == 3 and a[2] in ROLES:
        ok, note = set_role(int(a[1]), a[2])
        print(note); return 0 if ok else 1
    if a[0] == "--remove" and len(a) == 2:
        if not remove_user(int(a[1])):
            print("Can't remove the last admin."); return 1
        with state(write=False) as s:
            _show(s)
        return 0
    if a[0] == "--add":
        role = _role_flag(a) or "member"
        if len(a) != 2:
            print(__doc__); return 1
        uid = int(a[1])
        with state() as s:
            if s["roles"].get(str(uid)) != "admin" or role == "admin":
                s["roles"][str(uid)] = role
            _show(s)
        return 0
    role = _role_flag(a) or "member"
    if len(a) != 1:
        print(__doc__); return 1
    p = approve_code(a[0], role)
    if not p:
        print("Unknown or expired code."); return 1
    print(f"Approved user_id={p['user_id']} role={p['role']} username={p.get('username')} name={p.get('first_name')}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
