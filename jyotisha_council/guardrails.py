"""Guardrails in plain code: cheap, predictable and testable, in English, Nepali and Japanese.

1. check_question       runs BEFORE any LLM call and refuses off-limits questions.
2. evidence guardrail   runs on Parashar's draft: it must cite real, matched rule IDs.
3. safety guardrail     runs on the Guardian's final answer: no fear, no harm, no upsell,
                        and the evidence is checked again, because the Guardian rewrites text.
4. chat_guardrail       runs on every chat reply from the host.

Task guardrails return (False, feedback) to send the work back to the agent with the
reason, so the agent fixes it instead of the run failing. The evidence and safety
guardrails are built per consultation (make_*), so each reading checks its own matches.

Non-Latin scripts have no reliable word boundaries for regex, so Nepali and Japanese
patterns match phrases. They are a first line of defence, reviewed by tests/evals;
production would add a multilingual classifier.
"""

import re
from typing import Any, Callable, Tuple

RULE_ID = re.compile(r"\bR-[A-Z]{3}-[A-Z0-9]{2,3}\b")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")

# (pattern, topic). English patterns use word boundaries; ne/ja match phrases.
BLOCKED_QUESTIONS = [
    (r"\b(die|death|dying|lifespan|life span|how long will i live|longevity|ayu)\b", "death"),
    (r"(मर्छु|मर्ने|मर्नेछु|मृत्यु|आयु कति|कहिलेसम्म बाँच)", "death"),
    (r"(死ぬ|死亡|死期|いつ死|寿命|余命)", "death"),
    (r"\b(disease|illness|cancer|surgery|pregnan\w*|diagnos\w*|cure)\b", "health"),
    (r"(रोग|क्यान्सर|बिरामी|शल्यक्रिया|अपरेशन|गर्भ)", "health"),
    (r"(病気|がん|癌|ガン|手術|妊娠|診断)", "health"),
    (r"\b(court|lawsuit|legal case|verdict|jail|arrest\w*|bail)\b", "legal"),
    (r"(अदालत|जेल|पक्राउ|मुद्दा(मा| जित| हार))", "legal"),
    (r"(裁判|訴訟|逮捕|刑務所|判決)", "legal"),
    (r"\b(suicide|kill myself|self[- ]harm)\b", "self_harm"),
    (r"(आत्महत्या|आफैलाई मार्)", "self_harm"),
    (r"(自殺|死にたい|自傷)", "self_harm"),
]

UNSAFE_ANSWER_PATTERNS = [
    (r"\b(will|going to)\b[^.]{0,40}\b(die|death|disease|illness|accident|divorce|cancer)\b",
     "predicts death, illness, accident or divorce"),
    (r"(मृत्यु|दुर्घटना|रोग|क्यान्सर|सम्बन्ध विच्छेद|पारपाचुके)[^।]{0,25}(हुनेछ|लाग्नेछ)",
     "predicts death, illness, accident or divorce"),
    (r"(事故|死亡|死ぬ|病気|がん|癌|離婚)[^。]{0,12}(します|する|になる|になります|に遭|でしょう)",
     "predicts death, illness, accident or divorce"),
    (r"\b(curse\w*|doom\w*|cursed|black magic|evil eye)\b", "uses fear-mongering language"),
    (r"(श्राप|कालो जादु|बोक्सी|नजर लाग)", "uses fear-mongering language"),
    (r"(呪い|祟り|不吉|黒魔術)", "uses fear-mongering language"),
    (r"\b(buy|purchase|order)\b[^.]{0,50}\b(gemstone|gem|stone|yantra|rudraksha|puja|ritual)\b",
     "pushes a paid remedy"),
    (r"(रत्न|यन्त्र|रुद्राक्ष|पूजा)[^।]{0,25}(किन्|खरिद)", "pushes a paid remedy"),
    (r"(宝石|パワーストーン|お守り|ヤントラ|ルドラクシャ)[^。]{0,15}(買|購入)", "pushes a paid remedy"),
    (r"(₹|\$|\bRs\.?\s?\d|\bNPR\b|\bINR\b|¥\s?\d|\d+\s*円|रु\.?\s?\d)",
     "mentions prices or money for remedies"),
    (r"\b(guaranteed|definitely will|100%|certainly will)\b", "states a prediction as certain"),
    (r"(निश्चित रूपमा|ग्यारेन्टी|अवश्य हुनेछ|पक्कै[^।]{0,15}हुनेछ)", "states a prediction as certain"),
    (r"((必ず|絶対に|確実に)[^。]{0,20}(なります|でしょう|起こ|成功します|叶います)|保証します)",
     "states a prediction as certain"),
]

REFUSALS = {
    "en": {
        "death": "lifespan or death", "health": "health or medical matters", "legal": "legal outcomes",
        "template": ("I can't make predictions about {topic}. Jyotisha is a guide for reflection, not a "
                     "substitute for a doctor, lawyer or counsellor. Ask me about career, relationships, "
                     "studies, travel, finances or timing instead."),
        "self_harm": ("If you are having thoughts of harming yourself, please reach out to someone now. "
                      "In Nepal you can call the TUTH suicide prevention helpline at 1166."),
    },
    "ne": {
        "death": "आयु वा मृत्यु", "health": "स्वास्थ्य वा उपचार", "legal": "कानुनी नतिजा",
        "template": ("म {topic}बारे भविष्यवाणी गर्न सक्दिनँ। ज्योतिष चिन्तनका लागि मार्गदर्शन हो, डाक्टर, वकिल वा "
                     "परामर्शदाताको विकल्प होइन। बरु करियर, सम्बन्ध, पढाइ, यात्रा, आर्थिक अवस्था वा समयबारे सोध्नुहोस्।"),
        "self_harm": ("यदि तपाईंलाई आफूलाई हानि पुर्‍याउने विचार आइरहेको छ भने, कृपया अहिल्यै कसैसँग कुरा गर्नुहोस्। "
                      "नेपालमा TUTH आत्महत्या रोकथाम हेल्पलाइन 1166 मा फोन गर्न सक्नुहुन्छ।"),
    },
    "ja": {
        "death": "寿命や死", "health": "健康や医療", "legal": "法的な結果",
        "template": ("{topic}についての予測はできません。ジョーティシャは内省のための指針であり、医師・弁護士・"
                     "カウンセラーの代わりではありません。仕事、人間関係、学業、旅行、お金、タイミングについて聞いてください。"),
        "self_harm": ("自分を傷つけたいという気持ちがあるなら、今すぐ誰かに相談してください。"
                      "日本では「いのちの電話」（0570-783-556）に電話できます。"),
    },
}


def detect_language(text: str) -> str:
    if JAPANESE.search(text):
        return "ja"
    if DEVANAGARI.search(text):
        return "ne"
    return "en"


def check_question(question: str) -> tuple[bool, str]:
    """Refuse off-limits topics before any LLM call, replying in the question's language."""
    for pattern, topic in BLOCKED_QUESTIONS:
        if re.search(pattern, question, flags=re.IGNORECASE):
            text = REFUSALS[detect_language(question)]
            if topic == "self_harm":
                return False, text["self_harm"]
            return False, text["template"].format(topic=text[topic])
    return True, ""


def find_unsafe(text: str) -> str | None:
    """Return a description of the first unsafe pattern in `text`, or None."""
    for pattern, problem in UNSAFE_ANSWER_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return f"{problem} (found: '{match.group(0)}')"
    return None


def check_citations(text: str, matched: set[str]) -> str | None:
    """Every cited rule ID must be one the rule engine actually matched."""
    cited = set(RULE_ID.findall(text))
    if not cited:
        return ("Evidence Mode is required: cite at least one rule ID (e.g. R-CAR-01) from "
                "Shastra's findings next to the claim it supports.")
    invented = cited - matched
    if invented:
        return (f"You cited rule IDs that Shastra did not match: {sorted(invented)}. "
                f"Use only these: {sorted(matched)}.")
    return None


def make_evidence_guardrail(state: dict) -> Callable:
    def evidence_guardrail(output) -> Tuple[bool, Any]:
        problem = check_citations(output.raw, state["matched_rule_ids"])
        return (False, problem) if problem else (True, output.raw)
    return evidence_guardrail


def make_safety_guardrail(state: dict) -> Callable:
    def safety_guardrail(output) -> Tuple[bool, Any]:
        text = output.raw
        if problem := find_unsafe(text):
            return False, (f"The answer {problem}. Rewrite that part in calm, non-fatalistic "
                           "language. Keep every rule ID citation.")
        if problem := check_citations(text, state["matched_rule_ids"]):
            return False, f"After your review: {problem}"
        return True, text
    return safety_guardrail


READING_HEADINGS = re.compile(
    r"(Direct answer|Why \(Evidence Mode\)|Practical suggestion|सीधा उत्तर|किन \(प्रमाण\)|व्यावहारिक सुझाव|"
    r"結論|根拠（エビデンス）|実践的なアドバイス)\s*[:：]")


def looks_like_reading(text: str) -> bool:
    """A reading has the council's section headings or rule codes; small talk does not."""
    return len(set(READING_HEADINGS.findall(text))) >= 2 or bool(RULE_ID.search(text))


def chat_guardrail(output) -> Tuple[bool, Any]:
    """Runs on every chat reply from the host, including small talk."""
    if problem := find_unsafe(output.raw):
        return False, f"Your reply {problem}. Rewrite it calmly, without that."
    return True, output.raw


def make_chat_guardrail(session) -> Callable:
    """The orchestrator may not write a reading itself: readings must come through the council."""
    def orchestrator_guardrail(output) -> Tuple[bool, Any]:
        ok, result = chat_guardrail(output)
        if not ok:
            return ok, result
        if looks_like_reading(output.raw) and not session.delivered_reading:
            return False, ("You wrote a reading without the council. Do not interpret the chart "
                           "yourself: call handoff_to_ganita, then handoff_to_shastra, then send "
                           "your draft with handoff_to_guardian.")
        return True, output.raw
    return orchestrator_guardrail
