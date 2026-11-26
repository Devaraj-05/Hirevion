"""The rules that turn the third eye's detections into episodes (C7-1, owner, 2026-11-16): a
second person held 3 s, or any phone in view held 2 s. Detections are fixed numbers, not photos."""

from hirevion_vision_agent.watch import Detection, Ended, Started, Watch, seen

W, H = 1280, 720


def person(x: float, width: float = 400, height: float = 600, score: float = 0.9) -> Detection:
    return Detection("person", score, x, 60, width, height)


def phone(score: float = 0.6) -> Detection:
    return Detection("cell phone", score, 300, 400, 60, 110)


def run(watch: Watch, frames: list[tuple[float, dict[str, bool]]]) -> list[Started | Ended]:
    happened: list[Started | Ended] = []
    for at, flags in frames:
        happened += watch.update(at, flags)
    return happened


def both(person: bool = False, phone: bool = False) -> dict[str, bool]:
    return {"unexpected_person": person, "phone": phone}


def every(start: float, end: float, flags: dict[str, bool], step: float = 0.5):
    count = round((end - start) / step)
    return [(start + i * step, flags) for i in range(count + 1)]


class TestWhatAFrameShows:
    def test_two_people_is_a_second_person(self) -> None:
        assert seen([person(100), person(700)], W, H)["unexpected_person"] is True
        assert seen([person(100)], W, H)["unexpected_person"] is False

    def test_a_small_far_figure_doesnt_count_as_a_person(self) -> None:
        # A poster or a reflection far behind: under 2% of the picture.
        poster = person(900, width=60, height=90)
        assert seen([person(100), poster], W, H)["unexpected_person"] is False

    def test_any_phone_in_view_counts_but_not_a_weak_guess(self) -> None:
        assert seen([person(100), phone()], W, H)["phone"] is True
        assert seen([person(100), phone(score=0.3)], W, H)["phone"] is False


class TestEpisodes:
    def test_a_second_person_held_3_s_starts_an_episode_from_when_they_appeared(self) -> None:
        watch = Watch()
        assert run(watch, every(10, 12.5, both(person=True))) == []
        assert run(watch, [(13.0, both(person=True))]) == [Started("unexpected_person", 10.0)]

    def test_a_phone_needs_only_2_s(self) -> None:
        happened = run(Watch(), every(10, 12, both(phone=True)))
        assert happened == [Started("phone", 10.0)]

    def test_a_missed_frame_doesnt_reset_the_hold_but_a_real_gap_does(self) -> None:
        watch = Watch()
        flicker = [
            *every(10, 11, both(person=True)),
            (11.5, both()),
            *every(12, 13, both(person=True)),
        ]
        assert run(watch, flicker) == [Started("unexpected_person", 10.0)]
        gap = [*every(30, 31, both(person=True)), (31.5, both()), (32.5, both())]
        gap += every(33, 35.5, both(person=True))
        assert run(Watch(), gap) == []

    def test_an_episode_ends_5_s_after_the_last_sighting(self) -> None:
        watch = Watch()
        run(watch, every(10, 13, both(phone=True)))
        assert run(watch, every(13.5, 17.5, both())) == []
        assert run(watch, [(18.0, both())]) == [Ended("phone", 13.0, 10.0)]

    def test_the_same_kind_opens_at_most_one_episode_a_minute(self) -> None:
        watch = Watch()
        run(watch, every(10, 12, both(phone=True)))
        run(watch, every(12.5, 20, both()))  # ended
        assert run(watch, every(30, 33, both(phone=True))) == []
        run(watch, every(33.5, 40, both()))
        assert run(watch, every(75, 77, both(phone=True))) == [Started("phone", 75.0)]

    def test_a_person_and_a_phone_are_watched_apart(self) -> None:
        happened = run(Watch(), every(10, 13, both(person=True, phone=True)))
        assert happened == [Started("phone", 10.0), Started("unexpected_person", 10.0)]


class TestCooldownAndEnding:
    def test_an_episode_after_the_cooldown_starts_when_it_was_seen_then_not_a_minute_before(
        self,
    ) -> None:
        watch = Watch()
        run(watch, every(10, 12, both(phone=True)))  # first episode, started at 12
        run(watch, every(12.5, 20, both()))
        happened = run(watch, every(30, 80, both(phone=True)))  # in view all along
        (started,) = happened
        assert started.kind == "phone" and started.at >= 71.0

    def test_open_episodes_close_when_the_watch_ends(self) -> None:
        watch = Watch()
        run(watch, every(10, 13, both(phone=True, person=True)))
        assert watch.close_all() == [
            Ended("phone", 13.0, 10.0),
            Ended("unexpected_person", 13.0, 10.0),
        ]
        assert watch.close_all() == []


def screen(label: str = "tv", x: float = 900, score: float = 0.7) -> Detection:
    return Detection(label, score, x, 100, 260, 180)


class TestTheOtherSignals:
    """PRD §53's secondary screen and the candidate leaving the desk (C7-2, 2026-11-26)."""

    def test_a_second_screen_besides_the_candidates_own_is_a_secondary_screen(self) -> None:
        both = [person(100), screen("laptop", 200), screen("tv", 900)]
        assert seen(both, W, H)["secondary_screen"] is True
        laptops = [person(100), screen("laptop", 200), screen("laptop", 900)]
        assert seen(laptops, W, H)["secondary_screen"] is True

    def test_the_candidates_own_screen_or_a_weak_or_tiny_one_is_not(self) -> None:
        # A laptop, or a desktop PC's monitor (COCO's `tv`): the candidate's own screen.
        assert seen([person(100), screen("laptop", 200)], W, H)["secondary_screen"] is False
        assert seen([person(100), screen("tv", 900)], W, H)["secondary_screen"] is False
        weak = [person(100), screen("laptop", 200), screen(score=0.3)]
        assert seen(weak, W, H)["secondary_screen"] is False
        tiny = Detection("tv", 0.8, 900, 100, 40, 30)
        assert seen([person(100), screen("laptop", 200), tiny], W, H)["secondary_screen"] is False
        # One laptop found twice, boxes overlapping, is still one laptop.
        twice = [screen("laptop", 200), Detection("laptop", 0.6, 220, 110, 250, 170)]
        assert seen([person(100), *twice], W, H)["secondary_screen"] is False

    def test_no_person_in_the_picture_is_the_candidate_out_of_view(self) -> None:
        assert seen([], W, H)["left_view"] is True
        assert seen([person(100)], W, H)["left_view"] is False

    def test_a_secondary_screen_needs_5_s(self) -> None:
        flags = {"secondary_screen": True}
        assert run(Watch(), every(10, 14.5, flags)) == []
        assert run(Watch(), every(10, 15, flags)) == [Started("secondary_screen", 10.0)]

    def test_out_of_view_counts_only_once_the_candidate_was_seen(self) -> None:
        watch = Watch()
        # The picture is empty from the start (the phone shows the room before they sit).
        assert run(watch, every(0, 20, {"left_view": True})) == []
        run(watch, every(20.5, 30, {"left_view": False}))
        assert run(watch, every(30.5, 40, {"left_view": True})) == []
        assert run(watch, [(40.5, {"left_view": True})]) == [Started("left_view", 30.5)]

    def test_hands_movement_and_a_moved_phone_have_their_own_holds(self) -> None:
        assert run(Watch(), every(0, 14.5, {"hands_out_of_view": True})) == []
        assert run(Watch(), every(0, 15, {"hands_out_of_view": True})) == [
            Started("hands_out_of_view", 0.0)
        ]
        assert run(Watch(), every(0, 4, {"unusual_movement": True})) == [
            Started("unusual_movement", 0.0)
        ]
        assert run(Watch(), every(0, 5, {"view_changed": True})) == [Started("view_changed", 0.0)]


def test_a_kind_missing_from_a_frame_is_unknown_and_keeps_its_episode_open() -> None:
    """A covered picture says nothing about the candidate: their absence goes on (review)."""
    watch = Watch()
    run(watch, [(0.0, {"left_view": False})])
    assert run(watch, every(1, 11, {"left_view": True})) == [Started("left_view", 1.0)]
    assert run(watch, every(11.5, 30, {})) == []  # unreadable for 18 s: no end
    assert watch.last_seen("left_view") == 11.0
