import csv

import pytest

from blue_team import playbook_db, review


def queued(tmp_db, **kw):
    card = {"name": "relative_voice_clone", "title": "t", "status": "review", "summary": "s", "steps": ["a", "b"],
            "match": [{"priority": 100, "rule": {"feature": "payer_says", "op": "eq", "value": "family"}}],
            "evidence": {"cases": 8, "cluster_id": "c00"}, "gate_failures": [], "analyst": {"verdict": "new_scam"},
            "mule_accounts": [{"upi_id": "mule@ybl", "cases": 3}], "label_tx_ids": ["tx1", "tx2"], "reviews": []}
    card.update(kw)
    playbook_db.write(card, "review", tmp_db)


def test_two_different_analysts_approve_then_it_counts(tmp_db, tmp_path):
    queued(tmp_db)
    out = review.decide("relative_voice_clone", "Asha", "approve", root=tmp_db, exports=tmp_path / "x")
    assert out["status"] == "review" and out["approvals"] == ["asha"]
    with pytest.raises(review.ReviewError, match="already reviewed"):
        review.decide("relative_voice_clone", "asha ", "approve", root=tmp_db, exports=tmp_path / "x")
    out = review.decide("relative_voice_clone", "Ravi", "approve", root=tmp_db, exports=tmp_path / "x")
    assert out["status"] == "approved" and out["priority"] >= playbook_db.APPROVED_MIN_PRIORITY
    names = {pb.name: pb.status for pb in playbook_db.load(("known", "review", "approved"), tmp_db)}
    assert names["relative_voice_clone"] == "approved"
    rows = list(csv.DictReader(open(tmp_path / "x" / "relative_voice_clone" / "labels.csv", encoding="utf-8")))
    assert [r["tx_id"] for r in rows] == ["tx1", "tx2"]
    assert (tmp_path / "x" / "relative_voice_clone" / "mule_accounts.csv").exists()


def test_one_rejection_with_a_reason_stops_it(tmp_db):
    queued(tmp_db)
    with pytest.raises(review.ReviewError, match="note"):
        review.decide("relative_voice_clone", "asha", "reject", root=tmp_db)
    assert review.decide("relative_voice_clone", "asha", "reject", "same as digital_arrest", root=tmp_db)["status"] == "rejected"
    assert review.queue(tmp_db) == []
    with pytest.raises(review.ReviewError, match="rejected"):
        review.decide("relative_voice_clone", "ravi", "approve", root=tmp_db)


def test_a_card_failing_the_gates_cannot_be_approved(tmp_db):
    queued(tmp_db, gate_failures=["would name 3 legit payments per 1,000"])
    with pytest.raises(review.ReviewError, match="gates"):
        review.decide("relative_voice_clone", "asha", "approve", root=tmp_db)
