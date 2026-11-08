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
    from app.cloud_sync import UserStateChangesIn, UserStateIn, get_user_state, put_user_state, put_user_state_changes
    from fastapi import HTTPException

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

    # Two devices updating different keys must merge rather than replace snapshots.
    put_user_state_changes(UserStateChangesIn(set={"basket": ["device-one-item"]}), alice)
    put_user_state_changes(UserStateChangesIn(set={"strategy": "maximum-savings"}), alice)
    assert get_user_state(alice)["state"] == {
        "liked": ["recipe-alice-updated"],
        "basket": ["device-one-item"],
        "strategy": "maximum-savings",
    }

    # A deletion is retained as a tombstone and is visible to stale devices.
    put_user_state_changes(UserStateChangesIn(delete=["basket"]), alice)
    after_delete = get_user_state(alice)
    assert "basket" not in after_delete["state"]
    assert "basket" in after_delete["deleted_keys"]

    # A later explicit set revives a key and clears its tombstone.
    put_user_state_changes(UserStateChangesIn(set={"basket": ["new-device-item"]}), alice)
    revived = get_user_state(alice)
    assert revived["state"]["basket"] == ["new-device-item"]
    assert "basket" not in revived["deleted_keys"]

    # Cloud-state API must not accept catalog/cache payloads from a client.
    try:
        put_user_state_changes(UserStateChangesIn(set={"products": [{"id": 1}]}), alice)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Catalog state must never be accepted by cloud sync")

    # Legacy snapshot endpoint enforces the same key allowlist as delta writes.
    for invalid_state in ({"products": [{"id": 1}]}, {"liked": ["x"] * 100001}):
        try:
            put_user_state(UserStateIn(state=invalid_state), alice)
        except HTTPException as exc:
            assert exc.status_code in (413, 422)
        else:
            raise AssertionError("Legacy snapshot endpoint accepted an unsafe/oversized payload")
    assert get_user_state(alice)["state"] == revived["state"]

    # Existing accounts with only a legacy JSON snapshot migrate on first delta write.
    from app.database import SessionLocal, UserState
    db = SessionLocal()
    try:
        db.add(UserState(user_id="qa-legacy-user", state_json='{"liked":["legacy-pick"],"profile":{"servings":3},"products":[1]}'))
        db.commit()
    finally:
        db.close()
    legacy_user = request("qa-legacy-user", "legacy@example.test")
    put_user_state_changes(UserStateChangesIn(set={"basket": ["migrated-device-item"]}), legacy_user)
    assert get_user_state(legacy_user)["state"] == {
        "liked": ["legacy-pick"],
        "profile": {"servings": 3},
        "basket": ["migrated-device-item"],
    }, "Legacy state migration must preserve allowlisted keys and exclude catalog state"

    # New per-key writes remain scoped to the authenticated user ID.
    assert get_user_state(bob)["state"] == bob_state

    print("CLOUD SYNC QA PASS: account isolation, multi-device per-key merge, tombstones, legacy migration, key allowlist")
