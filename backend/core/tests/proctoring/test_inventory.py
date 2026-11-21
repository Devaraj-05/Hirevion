"""The process list taken when the interview starts (PROCESS_INVENTORY, ADR-0046)."""

from types import SimpleNamespace

from hirevion_core.proctoring.catalogue import MAX_INVENTORY, split_inventory
from hirevion_core.reports.proctoring import _evidence_detail


def test_the_list_leaves_the_details_and_keeps_only_its_fields() -> None:
    details, processes = split_inventory(
        {
            "count": 2,
            "processes": [
                {"name": "chrome.exe", "path": "C:\c.exe", "window_titles": ["A"] * 9, "text": "x"},
                {"name": "svchost.exe"},
                {"path": "no name"},
                "not a process",
            ],
        }
    )
    assert details == {"count": 2, "windows": ["chrome.exe"]}
    assert processes == [
        {"name": "chrome.exe", "path": "C:\c.exe", "window_titles": ["A"] * 5},
        {"name": "svchost.exe", "window_titles": []},
    ]


def test_the_list_is_bounded() -> None:
    _, processes = split_inventory({"processes": [{"name": "a" * 900}] * (MAX_INVENTORY + 5)})
    assert len(processes) == MAX_INVENTORY and len(processes[0]["name"]) == 300


def test_the_report_counts_the_processes() -> None:
    item = SimpleNamespace(kind="process_metadata", ref={"processes": [{}, {}, {}]}, bytes=None)
    assert _evidence_detail(item) == "3 running processes"
    blocked = SimpleNamespace(kind="process_metadata", ref={"name": "anydesk.exe"}, bytes=None)
    assert _evidence_detail(blocked) == "anydesk.exe"
