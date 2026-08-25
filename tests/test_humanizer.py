"""The free, deterministic humanizer: it strips AI tells without touching facts
or format, and it never runs a model. Pins behavior so a future edit can't make
it drop grounded content or empty a variable."""
from app.enrichment.pipeline import _dehype, _tidy_variable, _sanitize_fill


def test_jargon_is_swapped_for_plain_words():
    out = _dehype("We leverage a robust platform to seamlessly elevate results and empower your team.")
    for banned in ("leverage", "robust", "seamlessly", "elevate", "empower"):
        assert banned not in out.lower()
    assert "use" in out.lower() and "help" in out.lower()


def test_filler_greetings_and_closers_are_removed():
    out = _dehype("I hope this email finds you well. Your Halo launch hit 2.8x ROAS, which caught my eye.")
    assert "hope this email" not in out.lower()
    # the grounded fact survives verbatim
    assert "Halo" in out and "2.8x ROAS" in out


def test_empty_transitions_are_dropped_mid_text():
    out = _dehype("It works. Furthermore, it scales.")
    assert "furthermore" not in out.lower()
    assert "it scales" in out.lower()


def test_facts_numbers_and_clean_copy_are_left_alone():
    clean = "Your team grew 40% after the Series A, and the Titan rollout shipped in Q2."
    assert _dehype(clean) == clean


def test_case_is_preserved_on_swap():
    assert _dehype("Leverage this.").startswith("Use")


def test_tidy_variable_never_returns_empty_from_all_filler():
    # A line that is nothing but filler must not be blanked; keep the pre-scrub text.
    assert _tidy_variable("I look forward to hearing from you.").strip() != ""


def test_sanitize_fill_swaps_jargon_but_keeps_it_short():
    assert _sanitize_fill("leverage data") == "Use data" or _sanitize_fill("leverage data") == "use data"
