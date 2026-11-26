"""Demonstrate one shared MIMO history across two devices.

Start the backend, then run this from the repo root:

    uvicorn backend.api:app --host 127.0.0.1 --port 8000     # terminal 1
    python scripts/demo_two_devices.py                        # terminal 2

It pairs a pretend "phone" and "laptop" the way a real device pairs (a code shown on
the PC), writes a reminder from the phone, and reads it back from the laptop. Add
`--cleanup` to revoke both devices when it finishes.

This talks to the API over HTTP only, so it also works against a backend on another
machine on your LAN - pass --base-url.
"""
from __future__ import annotations

import argparse
import sys

import requests


def check(response, what):
    if response.status_code >= 400:
        raise SystemExit(f"{what} failed: {response.status_code} {response.text[:300]}")
    return response.json()


def pair(base: str, name: str, kind: str) -> dict:
    """The real flow: the PC shows a code, the device redeems it and keeps the token."""
    code = check(requests.post(f"{base}/auth/pair/code", timeout=10), "asking for a pairing code")["code"]
    body = check(requests.post(f"{base}/auth/pair", timeout=10,
                               json={"code": code, "name": name, "kind": kind}), f"pairing {name}")
    print(f"  {name:<12} paired as {body['device']['kind']}  token {body['token'][:14]}...")
    return {"id": body["device"]["id"], "token": body["token"],
            "headers": {"Authorization": f"Bearer {body['token']}"}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cleanup", action="store_true",
                        help="revoke both demo devices at the end")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")

    try:
        check(requests.get(f"{base}/health", timeout=10), "reaching the backend")
    except requests.RequestException:
        raise SystemExit(f"No MIMO backend at {base}. Start it first:\n"
                         f"  uvicorn backend.api:app --host 127.0.0.1 --port 8000")

    print("\n1. Pairing two devices")
    phone = pair(base, "Pixel", "android")
    laptop = pair(base, "Aadarsh-PC", "desktop")

    print("\n2. The phone starts a conversation")
    conversation = check(requests.post(f"{base}/conversations", json={"title": "Reminders"},
                                       headers=phone["headers"], timeout=10), "creating a conversation")
    cid = conversation["id"]
    print(f"  conversation {cid} created on the phone")

    message = "Tomorrow, remind me to continue my robotics project."
    check(requests.post(f"{base}/conversations/{cid}/messages", json={"role": "user", "content": message},
                        headers=phone["headers"], timeout=10), "sending the reminder")
    print(f'  phone:  "{message}"')

    print("\n3. Later, the laptop opens MIMO")
    listing = check(requests.get(f"{base}/conversations", headers=laptop["headers"], timeout=10),
                    "listing conversations")
    top = listing["conversations"][0]
    print(f'  laptop sees "{top["title"]}" ({top["message_count"]} message)')
    history = check(requests.get(f"{base}/conversations/{cid}/messages", headers=laptop["headers"],
                                 timeout=10), "reading the conversation")
    for row in history["messages"]:
        print(f'  laptop: {row["role"]:>9}: {row["content"]}')

    check(requests.post(f"{base}/conversations/{cid}/messages",
                        json={"role": "assistant", "content": "Noted for tomorrow morning."},
                        headers=laptop["headers"], timeout=10), "replying from the laptop")
    print('  laptop: assistant: "Noted for tomorrow morning."')

    print("\n4. The phone sees the laptop's reply in the same thread")
    history = check(requests.get(f"{base}/conversations/{cid}/messages", headers=phone["headers"],
                                 timeout=10), "re-reading from the phone")
    print(f'  phone:  {history["count"]} messages in one history, '
          f'origin device of the first: {history["messages"][0]["device_id"]}')

    if args.cleanup:
        for device in (phone, laptop):
            requests.delete(f"{base}/devices/{device['id']}", headers=laptop["headers"], timeout=10)
        print("\nDemo devices revoked.")

    print("\nSame conversation, same memory, two devices. That is the foundation under the apps.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
