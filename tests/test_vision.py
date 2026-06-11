import os
import tempfile

from goldscanner.models import Item, Score
from goldscanner.store import SeenStore
from goldscanner.vision import VisionScorer


class FakeSG:
    def download_image(self, url):
        return (b"fake-jpeg-bytes", "image/jpeg")


def make_scorer(verify_model="claude-opus-4-8"):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SeenStore(path)
    scorer = VisionScorer(
        client=FakeSG(),
        store=store,
        target_description="antique gold bangles",
        api_key="test-key",
        model="claude-haiku-4-5",
        verify_model=verify_model,
    )
    return scorer, store, path


def run_with_fake_models(scorer, results_by_model, calls):
    def fake_once(model, content, item):
        calls.append(model)
        return results_by_model[model]

    scorer._score_once = fake_once
    item = Item(item_id="1", title="Bangle", image_urls=["https://x/1.jpg"])
    return scorer.score(item)


def test_match_escalates_to_expert_model():
    scorer, store, path = make_scorer()
    try:
        calls = []
        result = run_with_fake_models(
            scorer,
            {
                "claude-haiku-4-5": Score(True, 0.6, "looks promising"),
                "claude-opus-4-8": Score(
                    True, 0.92, "genuine Victorian serpent bangle",
                    gold_type="solid_gold", looks_victorian=True,
                ),
            },
            calls,
        )
        assert calls == ["claude-haiku-4-5", "claude-opus-4-8"]
        # Expert verdict wins, and is labeled as such.
        assert result.confidence == 0.92
        assert result.reasoning.startswith("[Expert-verified]")
        assert result.gold_type == "solid_gold"
    finally:
        store.close()
        os.remove(path)


def test_clear_reject_skips_expert_model():
    scorer, store, path = make_scorer()
    try:
        calls = []
        result = run_with_fake_models(
            scorer,
            {"claude-haiku-4-5": Score(False, 0.1, "modern costume piece")},
            calls,
        )
        assert calls == ["claude-haiku-4-5"]
        assert result.confidence == 0.1
    finally:
        store.close()
        os.remove(path)


def test_borderline_reject_escalates():
    scorer, store, path = make_scorer()
    try:
        calls = []
        result = run_with_fake_models(
            scorer,
            {
                # Below min_confidence but above the verify threshold (0.35):
                # Haiku said no, but it's unsure — worth an expert look.
                "claude-haiku-4-5": Score(False, 0.5, "hard to tell"),
                "claude-opus-4-8": Score(True, 0.85, "it IS a period piece"),
            },
            calls,
        )
        assert calls == ["claude-haiku-4-5", "claude-opus-4-8"]
        assert result.is_match
    finally:
        store.close()
        os.remove(path)


def test_expert_failure_falls_back_to_screening_verdict():
    scorer, store, path = make_scorer()
    try:
        calls = []
        result = run_with_fake_models(
            scorer,
            {
                "claude-haiku-4-5": Score(True, 0.7, "looks good"),
                "claude-opus-4-8": Score(False, 0.0, "Scoring error: overloaded"),
            },
            calls,
        )
        assert calls == ["claude-haiku-4-5", "claude-opus-4-8"]
        assert result.is_match and result.confidence == 0.7
    finally:
        store.close()
        os.remove(path)


def test_verify_disabled_single_pass():
    scorer, store, path = make_scorer(verify_model=None)
    try:
        calls = []
        result = run_with_fake_models(
            scorer,
            {"claude-haiku-4-5": Score(True, 0.7, "looks good")},
            calls,
        )
        assert calls == ["claude-haiku-4-5"]
        assert result.confidence == 0.7
    finally:
        store.close()
        os.remove(path)
