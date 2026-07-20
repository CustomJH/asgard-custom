import threading

from asgard.agent.heimdall import Heimdall


def test_child_session_observer_tracks_role_status_and_completion():
    hd = object.__new__(Heimdall)
    hd._state_lock = threading.Lock()
    hd._session_seq = 0
    hd._sessions = {}
    labels = []
    hd.on_status = labels.append

    status, lifecycle = hd._session_observer("worker")
    lifecycle("running", "")
    status("$ pytest")

    assert hd.session_snapshot(active_only=True)[0]["status"] == "$ pytest"
    assert labels[-1] == "worker · $ pytest"

    lifecycle("finished", "done")
    assert hd.session_snapshot(active_only=True) == []
    assert hd.session_snapshot()[0]["state"] == "done"
