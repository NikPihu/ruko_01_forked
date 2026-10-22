"""The replay's episode watcher must feed the backend's state machine the way the phone does."""
from datetime import datetime, timedelta, timezone

from dataset.episodes import EpisodeFeed
from dataset.phone_view import Traits

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 10, 1, tzinfo=IST)
DAY0 = START + timedelta(days=10)  # after the watcher's warm-up


def traits(sms: bool, share: bool) -> Traits:
    return Traits(call_signals=True, app_checks=True, sms=sms, share_accounts=share, session_signals=True,
                  android_15=True)


def task_scam(feed: EpisodeFeed, uid: str) -> list[dict | None]:
    """Two rewards from a stranger, then 1,000 -> 2,500 -> 6,000 to new payees. Summaries before each payment."""
    feed.credit(uid, DAY0, 150, "task.reward@ybl", "scam_bait")
    feed.credit(uid, DAY0 + timedelta(hours=2), 200, "task.reward@ybl", "scam_bait")
    seen = []
    for i, amount in enumerate((1000, 2500, 6000)):
        ts = DAY0 + timedelta(hours=5 + 5 * i)
        seen.append(feed.summary(uid, ts.timestamp(), f"level{i}@okaxis"))
        feed.debit(uid, ts, amount, f"level{i}@okaxis")
    return seen


def test_task_scam_becomes_active_and_sharing_phones_queue_events():
    feed = EpisodeFeed({"u1": traits(True, True), "u2": traits(True, False)}, START)
    s1, s2 = task_scam(feed, "u1"), task_scam(feed, "u2")
    assert [s["state"] for s in s1] == ["watching", "watching", "watching"]
    assert feed.summary("u1", (DAY0 + timedelta(days=1)).timestamp(), "x@ybl")["state"] == "active"
    assert s1 == s2  # sharing changes what the server hears, not what the phone tracks
    events = feed.due(DAY0 + timedelta(days=1))
    assert events and {e["user_id"] for e in events} == {"u1"}  # u2 did not allow sharing
    assert {e["trigger"] for e in events} >= {"watching", "active"}
    assert feed.due(DAY0 + timedelta(days=1)) == []  # handed out once


def test_no_sms_checks_means_no_watcher_and_no_episode():
    feed = EpisodeFeed({"u1": traits(False, False)}, START)
    assert task_scam(feed, "u1") == [None, None, None]


def test_cashback_and_warm_up_credits_are_not_bait():
    feed = EpisodeFeed({"u1": traits(True, False)}, START)
    feed.credit("u1", DAY0, 40, "biller@okaxis", "cashback")                 # parser skips cashback alerts
    feed.credit("u1", START + timedelta(days=1), 150, "x@ybl", "scam_bait")  # during warm-up
    assert feed.summary("u1", (DAY0 + timedelta(hours=1)).timestamp(), "a@ybl")["state"] == "none"
