"""#1 Same scam, many phones: money handles counted across distinct users (graph/campaigns.py)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from graph import campaigns
from graph.campaigns import CampaignStore, hashed, normalise, wire_value

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
MULE = "secure.settlement.desk@okaxis"


def test_normalisation_matches_the_shared_vectors():
    """The phone hashes exactly like the server: both are checked against these vectors."""
    vec = json.loads((ROOT / "contracts" / "examples" / "handle_vectors.json").read_text(encoding="utf-8"))
    assert vec["salt"] == campaigns.SALT
    for v in vec["vectors"]:
        assert normalise(v["kind"], v["raw"]) == v["normalised"], v
        assert wire_value(v["kind"], v["raw"]) == v["wire"], v


def test_links_and_numbers_are_hashed_upi_ids_stay_plain():
    """Rule 2 / rule 7: the UPI ID is plain like any payee; link hosts and numbers are pseudonyms."""
    assert wire_value("upi", " Secure.Settlement.Desk@OKAXIS ") == MULE
    number = wire_value("phone", "+91 98123 45670")
    link = wire_value("link", "https://www.kyc-update-now.example/verify")
    for w in (number, link):
        assert w.startswith("sha256:") and "9812345670" not in w and "kyc" not in w
    # Every way of writing the same number becomes the same pseudonym.
    assert number == wire_value("phone", "098123-45670") == wire_value("phone", "9812345670")
    assert hashed("phone", "+919812345670", salt="other") != number


def test_a_handle_spreads_only_across_different_users():
    st = CampaignStore(window_minutes=60, min_users=3)
    for i in range(5):                                   # one phone getting the same scam five times
        st.record("u0", [("upi", MULE)], NOW + timedelta(minutes=i))
    assert st.users("upi", MULE, NOW + timedelta(minutes=5)) == 1 and not st.spreading("upi", MULE, NOW + timedelta(minutes=5))
    st.record("u1", [("upi", MULE)], NOW + timedelta(minutes=6))
    st.record("u2", [("upi", MULE.upper())], NOW + timedelta(minutes=7))
    assert st.spreading("upi", MULE, NOW + timedelta(minutes=8))


def test_old_sightings_drop_out_of_the_window_and_expire():
    st = CampaignStore(window_minutes=60, min_users=3, keep_hours=24)
    for i in range(3):
        st.record(f"u{i}", [("upi", MULE)], NOW)
    assert st.spreading("upi", MULE, NOW + timedelta(minutes=30))
    assert not st.spreading("upi", MULE, NOW + timedelta(minutes=61))   # outside the window
    st.expire(NOW + timedelta(hours=25))
    assert st.users("upi", MULE, NOW + timedelta(hours=25)) == 0 and not st.seen


def test_spreading_now_hides_hashed_handles():
    st = CampaignStore(window_minutes=60, min_users=3)
    number = wire_value("phone", "9812345670")
    for i in range(3):
        st.record(f"u{i}", [("upi", MULE), ("phone", number)], NOW)
    top = {t["kind"]: t for t in st.top(NOW)}
    assert top["upi"]["value"] == MULE and top["upi"]["users"] == 3 and top["upi"]["spreading"]
    assert top["phone"]["value"] is None and top["phone"]["users"] == 3


def test_campaign_numbers_come_from_policy_yaml():
    cfg = yaml.safe_load((ROOT / "backend" / "api" / "policy.yaml").read_text())["campaign"]
    assert campaigns.CAMPAIGN["min_users"] == cfg["min_users"] == CampaignStore().min_users
    assert CampaignStore().window == timedelta(minutes=cfg["window_minutes"])
