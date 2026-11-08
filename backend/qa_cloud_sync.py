"""Isolated user-state ownership QA; writes only to a temporary SQLite database."""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

with tempfile.TemporaryDirectory(prefix="bitewise-cloud-sync-qa-") as directory:
    os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(directory) / "cloud-sync.sqlite")
    os.environ["DATABASE_URL"] = ""
    os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

    from app.database import Base, engine
    from app.cloud_sync import UserStateIn, get_user_state, put_user_state

    Base.metadata.create_all(engine)

    def request(user_id, email):
        return SimpleNamespace(state=SimpleNamespace(
            bitewise_user={"id": user_id, "email": email}
        ))

    alice = request("qa-user-alice", "alice@example.test")
    bob = request("qa-user-bob", "bob@example.test")

    put_user_state(UserStateIn(state={
        "liked": ["recipe-alice"],
        "profile": {"servings": 1},
    }), alice)
    put_user_state(UserStateIn(state={
        "liked": ["recipe-bob"],
        "basket": ["product-bob"],
    }), bob)

    alice_state = get_user_state(alice)["state"]
    bob_state = get_user_state(bob)["state"]

    assert alice_state == {
        "liked": ["recipe-alice"],
        "profile": {"servings": 1},
    }, f"Alice's state was contaminated: {alice_state}"
    assert bob_state == {
        "liked": ["recipe-bob"],
        "basket": ["product-bob"],
    }, f"Bob's state was contaminated: {bob_state}"

    # Updating one user must not overwrite the other user's snapshot.
    put_user_state(UserStateIn(state={"liked": ["recipe-alice-updated"]}), alice)
    assert get_user_state(bob)["state"] == bob_state
    assert get_user_state(alice)["state"] == {"liked": ["recipe-alice-updated"]}

    print("CLOUD SYNC QA PASS: independent user IDs, isolated reads/writes, overwrite isolation")
