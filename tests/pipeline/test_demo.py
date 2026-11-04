from telltale.pipeline.demo import DEMO, demo_seed

CLIPS = ("cand36", "cand37", "cand38", "cand63")
STORIES = [story for _, story in DEMO]


def test_seed_is_deterministic():
    assert demo_seed("cand36", "perception_late") == demo_seed("cand36", "perception_late")


def test_every_clip_draws_different_numbers_for_the_same_story():
    """The same seed on two clips made cand36 and cand38 show identical latencies, which looked templated."""
    for story in STORIES:
        seeds = [demo_seed(clip, story) for clip in CLIPS]
        assert len(set(seeds)) == len(CLIPS), story


def test_log_letters_keep_the_same_story_order_on_every_clip():
    """The UI labels a clip's logs A-E in case-id order, so seeds must ascend in story order within a clip."""
    for clip in CLIPS:
        seeds = [demo_seed(clip, story) for story in STORIES]
        assert seeds == sorted(seeds), clip


def test_seeds_stay_four_digits_so_case_ids_sort_correctly():
    for clip in CLIPS:
        for story in STORIES:
            assert 1000 <= demo_seed(clip, story) <= 9999
