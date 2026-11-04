from telltale.pipeline.demo import DEMO, DEMO_STORIES, demo_seed

CLIPS = ("cand36", "cand37", "cand38", "cand63")


def test_seed_is_deterministic():
    assert demo_seed("cand36", "perception_late") == demo_seed("cand36", "perception_late")


def test_every_clip_draws_different_numbers_for_the_same_story():
    """The same seed on two clips made cand36 and cand38 show identical latencies, which looked templated."""
    for profile in ("car", "truck"):
        for story in DEMO_STORIES:
            seeds = [demo_seed(clip, story, profile) for clip in CLIPS]
            assert len(set(seeds)) == len(CLIPS), story


def test_log_letters_keep_the_same_story_order_on_every_clip():
    """The UI labels a clip's logs A-E in case-id order, so seeds must ascend in story order within a clip."""
    for profile in ("car", "truck"):
        for clip in CLIPS:
            seeds = [demo_seed(clip, story, profile) for story in DEMO_STORIES]
            assert seeds == sorted(seeds), clip


def test_seeds_stay_four_digits_so_case_ids_sort_correctly():
    for profile in ("car", "truck"):
        for clip in CLIPS:
            for story in DEMO_STORIES:
                assert 1000 <= demo_seed(clip, story, profile) <= 9999


def test_car_seeds_are_unchanged_by_the_truck_cases():
    """The published car demo cases must regenerate byte-for-byte."""
    assert demo_seed("cand36", "perception_late") == 1775
    assert demo_seed("cand63", "late_handoff", "car") == 4909


def test_truck_cases_cover_every_story_with_their_own_numbers():
    assert {s for p, s in DEMO if p == "truck"} == set(DEMO_STORIES)
    for clip in CLIPS:
        for story in DEMO_STORIES:
            assert demo_seed(clip, story, "truck") != demo_seed(clip, story, "car")
