"""Regression checks for intelligent Client Brain updates.

Run directly: python tests/test_brain_merge.py
"""
from app.enrichment.brain import accumulate_brain, merge_brain_list


def test_case_study_is_enriched_field_by_field():
    existing = [{
        "client": "Acme",
        "industry": "Manufacturing",
        "problem": "Slow quoting",
        "metrics": ["20% faster"],
    }]
    fresh = [{
        "client": "Acme",
        "solution": "Automated the quoting workflow",
        "outcome": "Won more enterprise deals",
        "metrics": ["20% faster.", "12 new deals"],
    }]

    merged = merge_brain_list("case_studies", existing, fresh)

    assert len(merged) == 1
    assert merged[0]["problem"] == "Slow quoting"
    assert merged[0]["solution"] == "Automated the quoting workflow"
    assert merged[0]["outcome"] == "Won more enterprise deals"
    assert merged[0]["metrics"] == ["20% faster", "12 new deals"]


def test_matching_problem_library_accumulates_pains_and_updates_angle():
    existing = [{"industry": "SaaS", "pains": ["Long sales cycles"], "our_angle": "Old angle"}]
    fresh = [{"industry": "SaaS", "pains": ["Long sales cycles.", "Weak follow-up"], "our_angle": "New angle"}]

    merged = merge_brain_list("problem_library", existing, fresh)

    assert len(merged) == 1
    assert merged[0]["pains"] == ["Long sales cycles", "Weak follow-up"]
    assert merged[0]["our_angle"] == "New angle"


def test_explicit_shorter_scalar_correction_replaces_old_value():
    existing = {"main_offer": "A very long description of an outdated consulting service"}
    fresh = {"main_offer": "Managed outbound"}

    merged = accumulate_brain(existing, fresh, scalar_strategy="replace")

    assert merged["main_offer"] == "Managed outbound"


def test_website_refresh_preserves_richer_curated_scalar():
    existing = {"main_offer": "Detailed managed outbound and post-meeting follow-up for B2B teams"}
    fresh = {"main_offer": "Managed outbound"}

    merged = accumulate_brain(existing, fresh, scalar_strategy="richer")

    assert merged["main_offer"] == existing["main_offer"]


def test_plain_lists_dedupe_cosmetic_variations():
    merged = merge_brain_list(
        "services",
        ["Managed outbound", "Meeting follow-up"],
        ["managed outbound.", "Pipeline strategy"],
    )

    assert merged == ["Managed outbound", "Meeting follow-up", "Pipeline strategy"]


def run():
    checks = [
        test_case_study_is_enriched_field_by_field,
        test_matching_problem_library_accumulates_pains_and_updates_angle,
        test_explicit_shorter_scalar_correction_replaces_old_value,
        test_website_refresh_preserves_richer_curated_scalar,
        test_plain_lists_dedupe_cosmetic_variations,
    ]
    for check in checks:
        check()
    print(f"OK: {len(checks)} Client Brain merge checks passed")


if __name__ == "__main__":
    run()
