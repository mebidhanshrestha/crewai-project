"""Tests for the deterministic layer (no LLM, no API key needed)."""

import json
import random
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from astro.ganita import compute_chart
from astro.shastra import evidence_strength, humanize, load_rules, match_rules
from guardrails import (chat_guardrail, check_question, detect_language, find_unsafe,
                        make_evidence_guardrail, make_safety_guardrail)
from tools import ChartCalculatorTool, RuleLookupTool, new_state

ON = datetime(2026, 10, 17, tzinfo=ZoneInfo("UTC"))
CHART = compute_chart("2000-01-01", "17:45", 27.7172, 85.3240, "Asia/Kathmandu", on=ON)
out = lambda text: SimpleNamespace(raw=text)  # noqa: E731


# --- Ganita -------------------------------------------------------------------

def test_sun_position_matches_ephemeris():
    # Sidereal Sun on 1 Jan 2000 is ~16.5 degrees Sagittarius.
    assert CHART["planets"]["Sun"]["sign"] == "Sagittarius"
    assert abs(CHART["planets"]["Sun"]["degree"] - 16.5) < 0.5


def test_dasha_sequence():
    # Moon in Swati (Rahu) -> Jupiter -> Saturn mahadasha running in 2026.
    assert CHART["nakshatra"] == "Swati"
    assert CHART["dasha"]["mahadasha"] == "Saturn"


# --- Shastra ------------------------------------------------------------------

def test_rules_are_unique_labelled_in_three_languages_and_toned():
    rules = load_rules()
    assert len({r["id"] for r in rules}) == len(rules)
    for r in rules:
        assert set(r["label"]) == {"en", "ne", "ja"} and all(r["label"].values())
        assert r["tone"] in ("supportive", "caution")
    assert sum(r["tone"] == "caution" for r in rules) >= 6  # readings are not one-sided


def test_matching_is_deterministic_and_localised():
    assert match_rules(CHART, "career") == match_rules(CHART, "career")
    ja = {m["rule_id"]: m["label"] for m in match_rules(CHART, "career", "Japanese")}
    assert ja["R-GEN-01"] == "知恵と周囲からの支え"  # Gaja Kesari


def test_confidence_is_calibrated_against_base_rates():
    """'strong' should be roughly the top quarter of charts, not most people."""
    rng = random.Random(123)
    counts = Counter()
    for _ in range(300):
        d = datetime(1960, 1, 1) + timedelta(minutes=rng.randrange(50 * 365 * 24 * 60))
        chart = compute_chart(d.strftime("%Y-%m-%d"), d.strftime("%H:%M"), 27.7, 85.3, "Asia/Kathmandu")
        counts[evidence_strength(chart, "career")["strength"]] += 1
    assert 0.12 < counts["strong"] / 300 < 0.40


def test_humanize_swaps_codes_for_labels():
    assert humanize("Growth [R-CAR-01].") == "Growth (A career set to grow steadily)."
    assert "着実に伸びるキャリア" in humanize("[R-CAR-01]", "Japanese")
    assert "क्रमशः बढ्ने करियर" in humanize("R-CAR-01", "Nepali")


# --- Per-consultation state -----------------------------------------------------

def test_each_consultation_has_its_own_state():
    a = new_state({"date": "2000-01-01", "time": "17:45", "latitude": 27.7, "longitude": 85.3,
                   "timezone": "Asia/Kathmandu"})
    b = new_state({"date": "1990-06-15", "time": "08:20", "latitude": 28.2, "longitude": 83.9,
                   "timezone": "Asia/Kathmandu"})
    ChartCalculatorTool(state=a)._run()
    ChartCalculatorTool(state=b)._run()
    RuleLookupTool(state=a)._run(topic="career")
    assert a["chart"] != b["chart"]
    assert a["matched_rule_ids"] and not b["matched_rule_ids"]


# --- Guardrails ------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "When will I die?", "Will I win my court case?", "Do I have cancer?",
    "म कहिले मर्छु?", "मलाई क्यान्सर हुन्छ कि?", "अदालतमा मुद्दा जित्छु?",
    "私はいつ死ぬ？", "寿命はどれくらい？", "病気になりますか？", "裁判に勝てますか？",
])
def test_input_guardrail_blocks_in_three_languages(question):
    assert check_question(question)[0] is False


@pytest.mark.parametrize("question", [
    "Should I take the Japan job offer?", "मेरो करियर कस्तो छ?", "करियरको मुद्दा के हो?",
    "日本で働くべきですか？", "必死に勉強しています。試験はどうなりますか？",
])
def test_input_guardrail_allows_normal_questions(question):
    assert check_question(question)[0] is True


def test_refusal_is_in_the_question_language():
    assert detect_language(check_question("私はいつ死ぬ？")[1]) == "ja"
    assert detect_language(check_question("म कहिले मर्छु?")[1]) == "ne"
    assert "1166" in check_question("I want to kill myself")[1]


@pytest.mark.parametrize("text", [
    "You will have an accident.", "तपाईंको दुर्घटना हुनेछ।", "事故に遭うでしょう。",
    "Buy a blue sapphire gemstone.", "रत्न किन्नुहोस्।", "パワーストーンを買ってください。",
    "This is guaranteed.", "必ず成功します。", "Book a puja for ₹5000.",
])
def test_output_guardrail_flags_unsafe_text_in_three_languages(text):
    assert find_unsafe(text) is not None


@pytest.mark.parametrize("text", [
    "A steady period for growth.", "必ず休息を取りましょう。", "धैर्यले फल दिनेछ।",
])
def test_output_guardrail_allows_calm_advice(text):
    assert find_unsafe(text) is None


def test_evidence_guardrail_rejects_invented_or_missing_rules():
    state = {"matched_rule_ids": {"R-CAR-01"}}
    check = make_evidence_guardrail(state)
    assert check(out("Good career [R-CAR-01]"))[0] is True
    assert check(out("Good career [R-CAR-09]"))[0] is False
    assert check(out("Good career."))[0] is False


def test_safety_guardrail_rechecks_evidence_after_guardian_rewrite():
    state = {"matched_rule_ids": {"R-DAS-SAT"}}
    check = make_safety_guardrail(state)
    assert check(out("A steady period [R-DAS-SAT]"))[0] is True
    assert check(out("A steady period [R-DAS-JUP]"))[0] is False  # Guardian swapped in an unmatched rule
    assert check(out("You will face an accident [R-DAS-SAT]"))[0] is False


def test_chat_guardrail():
    assert chat_guardrail(out("Namaste! How can I help?"))[0] is True
    assert chat_guardrail(out("You are cursed."))[0] is False


# --- Store ---------------------------------------------------------------------------

def test_profiles_are_encrypted_and_can_be_forgotten(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "PROFILES_PATH", tmp_path / "profiles.enc")
    monkeypatch.setattr(store, "LEDGER_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr(store, "KEY_PATH", tmp_path / ".key")
    monkeypatch.delenv("PROFILE_KEY", raising=False)

    store.save_profile({"name": "Asha", "date": "1999-01-01"})
    store.append_prediction("Asha", "Career?", "Steady [R-CAR-01]", ["R-CAR-01"])
    assert b"Asha" not in (tmp_path / "profiles.enc").read_bytes()  # encrypted at rest
    assert store.get_profile("asha")["date"] == "1999-01-01"

    result = store.forget_person("Asha")
    assert result == {"profile_deleted": True, "readings_deleted": 1}
    assert store.get_profile("Asha") is None and store.ledger_for("Asha") == []


def test_session_ids_are_validated():
    import store
    with pytest.raises(ValueError):
        store.load_session("../../etc/passwd")
