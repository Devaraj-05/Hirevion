"""The briefing tells the desktop which running apps must be closed before Start (C8-6)."""

from hirevion_core.interview_session.briefing import app_rules_to_close
from hirevion_core.proctoring.policy import base_policy

RULE = {"match": "publisher", "value": "TeamViewer Germany GmbH", "category": "remote_access"}


def test_the_rules_come_with_a_policy_that_checks_processes() -> None:
    policy = base_policy("standard", blocked=[RULE])
    assert app_rules_to_close(policy) == {"blocked": [RULE], "allowed": []}


def test_no_rules_when_the_policy_doesnt_check_processes() -> None:
    assert app_rules_to_close(base_policy("basic", blocked=[RULE])) is None
    assert app_rules_to_close(base_policy("off", blocked=[RULE])) is None
