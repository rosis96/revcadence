"""Pure regression checks for evidence planning and local candidate ranking.

Run: python -m tests.test_writer_quality
"""
from app.enrichment.writer_quality import (
    enrich_signal,
    local_candidate_score,
    plan_core_assignments,
    supporting_detail_matches,
)


def _signal(kind, score, text, quote, url):
    return enrich_signal({
        "type": kind,
        "score": score,
        "text": text,
        "key": text.lower(),
        "supporting_quote": quote,
        "source_url": url,
        "confidence": 1,
    })


def test_unbox_plan_uses_the_best_fact_for_each_job():
    signals = [
        _signal(
            "case_study", 10,
            "Dr. Alexander Shor said the FirstPlug collaboration exceeded expectations",
            "Our collaboration exceeded expectations in design and creativity.",
            "https://unboxpd.com/firstplug",
        ),
        _signal(
            "result", 10,
            "Monstatek's M1 reached market in under 12 months and secured $2.8 million in crowdfunding",
            "M1 was developed in under 12 months and validated through $2.8 million in crowdfunding.",
            "https://unboxpd.com/monstatek",
        ),
        _signal(
            "case_study", 10,
            "FirstPlug is the first and only FDA-approved dental-implant restoration solution",
            "FirstPlug became the first and only FDA-approved solution for dental implant restoration.",
            "https://unboxpd.com/firstplug",
        ),
        _signal(
            "project", 8,
            "Cambot 360 AI-Powered 3D Camera",
            "Four 4K lenses create auto-stitched 16K views with AI autofocus and lens protection.",
            "https://unboxpd.com/cambot-360",
        ),
        _signal(
            "award", 9,
            "More than 30 international design awards",
            "Our work has received more than 30 international design awards.",
            "https://unboxpd.com/about",
        ),
    ]

    plan = plan_core_assignments(
        signals, ["first_line", "value_proposition", "product_compliment"])

    assert "Monstatek" in plan["first_line"]["text"]
    assert "FirstPlug" in plan["value_proposition"]["text"]
    assert "FDA-approved" in plan["value_proposition"]["text"]
    assert "Cambot 360" in plan["product_compliment"]["text"]


def test_product_name_alone_does_not_count_as_using_the_detail():
    assignment = {
        "evidence": "Cambot 360 AI-Powered 3D Camera",
        "supporting_quote": "Four 4K lenses create auto-stitched 16K views with AI autofocus.",
    }

    assert not supporting_detail_matches(
        "Cambot 360 is technically sophisticated. Is it popular?", assignment)
    assert supporting_detail_matches(
        "Cambot 360's four 4K lenses creating auto-stitched 16K views are ambitious. "
        "Is it a flagship project?", assignment)


def test_local_ranker_prefers_specific_candidate():
    assignment = {
        "evidence": "Cambot 360 AI-Powered 3D Camera",
        "supporting_quote": "Four 4K lenses create auto-stitched 16K views with AI autofocus.",
    }
    fmt = {"name": "product_complimentary", "min_words": 10, "max_words": 35}
    generic = "Cambot 360 is technically sophisticated. Has it become popular with clients?"
    specific = (
        "Cambot 360's four 4K lenses producing auto-stitched 16K views are ambitious. "
        "Is it a flagship project?"
    )

    assert local_candidate_score(
        specific, "product_compliment", assignment, fmt
    ) > local_candidate_score(generic, "product_compliment", assignment, fmt)


def run():
    checks = [
        test_unbox_plan_uses_the_best_fact_for_each_job,
        test_product_name_alone_does_not_count_as_using_the_detail,
        test_local_ranker_prefers_specific_candidate,
    ]
    for check in checks:
        check()
    print(f"OK: {len(checks)} writer-quality checks passed")


if __name__ == "__main__":
    run()
