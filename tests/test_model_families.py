#!/usr/bin/env python3
"""Tests for the superseded-version dedupe (scripts/model_families.py).

Every case here is a shape the live llm-stats leaderboard has actually served
or plausibly will. The dedupe decides what the public site shows, so a
regression is user-visible: either a model appears twice at two versions, or a
legitimate distinct tier silently vanishes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from model_families import model_family_key, model_version_key, superseded_models


def dropped(names):
    """Names removed by the dedupe, in leaderboard order."""
    s = superseded_models(names)
    return [names[i] for i in sorted(s)]


def kept(names):
    s = superseded_models(names)
    return [n for i, n in enumerate(names) if i not in s]


class FamilyKeyTests(unittest.TestCase):
    def test_version_suffix_is_stripped(self):
        self.assertEqual(model_family_key("Claude Opus 5"), "claude opus")
        self.assertEqual(model_family_key("Claude Opus 4.8"), "claude opus")

    def test_version_glued_to_prefix_is_stripped(self):
        # "V4", "K3", "Qwen3.8", "GLM-5.3" all carry the version inside a token.
        self.assertEqual(model_family_key("DeepSeek-V4-Pro-0813"), "deepseek v pro")
        self.assertEqual(model_family_key("Kimi K3"), "kimi k")
        self.assertEqual(model_family_key("Qwen3.8 Max"), "qwen max")
        self.assertEqual(model_family_key("GLM-5.3-Flash"), "glm flash")

    def test_tier_words_are_preserved(self):
        # The whole point: Opus/Sonnet/Fable are different models, not versions.
        keys = {
            model_family_key(n)
            for n in ("Claude Opus 5", "Claude Sonnet 5", "Claude Fable 5")
        }
        self.assertEqual(len(keys), 3)

    def test_separators_are_equivalent(self):
        self.assertEqual(
            model_family_key("GPT-5.6 Sol"), model_family_key("GPT 5.6 Sol")
        )


class VersionKeyTests(unittest.TestCase):
    def test_orders_within_a_family(self):
        self.assertLess(
            model_version_key("Claude Opus 4.8"), model_version_key("Claude Opus 5")
        )

    def test_minor_versions_order_numerically(self):
        # String comparison would put "5.10" before "5.9"; tuples must not.
        self.assertLess(model_version_key("GLM-5.9"), model_version_key("GLM-5.10"))

    def test_first_number_is_the_version_not_the_checkpoint(self):
        # "0813" is an MMDD stamp, not a version — V4 must not read as v0813.
        self.assertLess(
            model_version_key("DeepSeek-V4-Pro-0813"),
            model_version_key("DeepSeek-V5-Pro-0101"),
        )

    def test_checkpoint_breaks_ties_within_a_version(self):
        self.assertLess(
            model_version_key("DeepSeek-V4-Flash-0731"),
            model_version_key("DeepSeek-V4-Flash-0813"),
        )

    def test_unversioned_name_has_no_version(self):
        self.assertIsNone(model_version_key("Command R"))


class SupersededTests(unittest.TestCase):
    def test_user_reported_case_fable(self):
        # The case that prompted this feature, seen live on 2026-09-02.
        self.assertEqual(
            dropped(["Claude Fable 5.1", "Claude Fable 5"]), ["Claude Fable 5"]
        )

    def test_live_us_cohort_2026_09_02(self):
        names = [
            "GPT-5.6 Sol", "Claude Opus 5", "Claude Fable 5.1", "GPT-5.6 Terra",
            "Claude Opus 4.8", "Muse Spark 1.1", "Gemini 3.7 Flash",
            "Claude Sonnet 5", "GPT-5.5", "Claude Fable 5",
        ]
        self.assertEqual(
            dropped(names), ["Claude Opus 4.8", "GPT-5.5", "Claude Fable 5"]
        )

    def test_sibling_tiers_all_survive(self):
        names = ["Claude Opus 5", "Claude Sonnet 5", "Claude Fable 5"]
        self.assertEqual(dropped(names), [])

    def test_flash_variant_is_not_superseded_by_flagship(self):
        # GLM-5.3 and GLM-5.3-Flash are different products at the same version.
        self.assertEqual(dropped(["GLM-5.3", "GLM-5.3-Flash"]), [])

    def test_variants_never_supersede_each_other(self):
        """A first GPT-6 listing must not wipe the GPT-5.6 tiers.

        On 2026-09-04 'GPT-6 Astra' caused Sol, Terra and Luna to be skipped
        as superseded, then was dropped for coverage itself — OpenAI ended
        with no models on the board.
        """
        names = ["GPT-6 Astra", "GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.6 Luna", "GPT-5.5"]
        self.assertEqual(dropped(names), ["GPT-5.5"])

    def test_bare_name_loses_to_a_newer_untiered_release_too(self):
        self.assertEqual(dropped(["GPT-6 Astra", "GPT-5.5"]), ["GPT-5.5"])

    def test_bare_name_folds_into_variants(self):
        # Chosen behaviour: GPT-5.5 loses to GPT-5.6 Sol / Terra.
        self.assertEqual(dropped(["GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.5"]), ["GPT-5.5"])

    def test_version_tie_keeps_both_siblings(self):
        # Sol and Terra are siblings, not successors — neither supersedes.
        self.assertEqual(dropped(["GPT-5.6 Sol", "GPT-5.6 Terra"]), [])

    def test_result_is_independent_of_leaderboard_order(self):
        # The newer sibling is not guaranteed to rank above the older one, so
        # the outcome must not depend on the order rows arrive in.
        base = ["GPT-5.6 Sol", "GPT-5.5", "GPT-5.6 Terra"]
        for order in ([0, 1, 2], [1, 0, 2], [2, 1, 0], [1, 2, 0]):
            names = [base[i] for i in order]
            self.assertEqual(dropped(names), ["GPT-5.5"], f"order {order}")

    def test_deep_variant_chain_does_not_absorb_its_prefix(self):
        # An experimental vision variant must not evict the plain Flash model,
        # even at a higher version — the single-token brand-root guard.
        names = ["DeepSeek-V4-Flash", "DeepSeek-V5-Flash-Vision-Exp"]
        self.assertEqual(dropped(names), [])

    def test_checkpoint_restamp_supersedes(self):
        names = ["DeepSeek-V4-Flash-0731", "DeepSeek-V4-Flash-0813"]
        self.assertEqual(dropped(names), ["DeepSeek-V4-Flash-0731"])

    def test_unversioned_names_are_never_dropped(self):
        self.assertEqual(dropped(["Command R", "Command R+"]), [])

    def test_unversioned_original_is_superseded_by_a_versioned_sibling(self):
        """An unversioned name in a versioned family is the v1.0 original.

        2026-09-04: the April "Muse Spark" took the US slot that "Muse Spark
        1.3" had been excluded from. It is the older product, not an alias.
        """
        self.assertEqual(dropped(["Muse Spark", "Muse Spark 1.3"]), ["Muse Spark"])
        self.assertEqual(dropped(["Grok 4.5", "Grok"]), ["Grok"])

    def test_unversioned_name_with_no_versioned_sibling_is_kept(self):
        self.assertEqual(dropped(["Command R", "Kimi K3"]), [])

    def test_empty_and_single_inputs(self):
        self.assertEqual(dropped([]), [])
        self.assertEqual(dropped(["Claude Opus 5"]), [])

    def test_more_than_two_versions_keeps_only_newest(self):
        names = ["Claude Opus 4.8", "Claude Opus 5", "Claude Opus 4.9"]
        self.assertEqual(kept(names), ["Claude Opus 5"])

    def test_winner_reported_is_the_newest(self):
        names = ["Claude Opus 4.8", "Claude Opus 5"]
        self.assertEqual(superseded_models(names)[0], "Claude Opus 5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
