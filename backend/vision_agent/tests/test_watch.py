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
