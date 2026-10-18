"""Shared settings: environment, places, languages, disclaimer and error messages."""

import os

from dotenv import load_dotenv

load_dotenv()

from observability import setup_tracing  # noqa: E402

setup_tracing()  # before CrewAI is imported anywhere, so its agents and LLM calls are traced

# Small built-in gazetteer: (latitude, longitude, timezone)
PLACES = {
    "kathmandu": (27.7172, 85.3240, "Asia/Kathmandu"),
    "lalitpur": (27.6588, 85.3247, "Asia/Kathmandu"),
    "bhaktapur": (27.6710, 85.4298, "Asia/Kathmandu"),
    "pokhara": (28.2096, 83.9856, "Asia/Kathmandu"),
    "biratnagar": (26.4525, 87.2718, "Asia/Kathmandu"),
    "bharatpur": (27.6833, 84.4333, "Asia/Kathmandu"),
    "butwal": (27.7006, 83.4483, "Asia/Kathmandu"),
    "dharan": (26.8065, 87.2846, "Asia/Kathmandu"),
    "janakpur": (26.7288, 85.9263, "Asia/Kathmandu"),
    "nepalgunj": (28.0500, 81.6167, "Asia/Kathmandu"),
    "delhi": (28.6139, 77.2090, "Asia/Kolkata"),
    "mumbai": (19.0760, 72.8777, "Asia/Kolkata"),
    "varanasi": (25.3176, 82.9739, "Asia/Kolkata"),
    "tokyo": (35.6762, 139.6503, "Asia/Tokyo"),
    "osaka": (34.6937, 135.5023, "Asia/Tokyo"),
}

LANGUAGE_NAMES = ["English", "Nepali", "Japanese"]

DISCLAIMER = {
    "English": ("Jyotisha is offered for reflection and guidance, not as certainty. Your choices "
                "shape your life. For health, legal or money decisions, please consult a qualified "
                "professional."),
    "Nepali": ("ज्योतिष चिन्तन र मार्गदर्शनका लागि हो, निश्चितताका लागि होइन। तपाईंका निर्णयले नै जीवन बनाउँछ। "
               "स्वास्थ्य, कानुनी वा आर्थिक निर्णयका लागि योग्य विशेषज्ञसँग सल्लाह लिनुहोस्।"),
    "Japanese": ("ジョーティシャは内省と指針のためのものであり、確実な予言ではありません。人生を形づくるのはあなたの選択です。"
                 "健康・法律・お金に関する判断は、専門家に相談してください。"),
}


def normalize_language(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v.startswith(("nep", "ne")) or "नेपाली" in v:
        return "Nepali"
    if v.startswith(("jap", "ja", "jp")) or "日本" in v:
        return "Japanese"
    return "English"


def missing_key() -> str | None:
    provider = os.getenv("LLM_MODEL", "openai/").split("/")[0]
    needed = {"openai": ["OPENAI_API_KEY"], "anthropic": ["ANTHROPIC_API_KEY"],
              "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]}
    if provider in needed and not any(os.getenv(k) for k in needed[provider]):
        return f"Missing {needed[provider][0]}. Copy .env.example to .env and add your key."
    return None


def explain_llm_error(exc: Exception) -> str:
    """Turn provider errors into one actionable line instead of a traceback."""
    text = str(exc).lower()
    if "insufficient_quota" in text or ("exceeded your current quota" in text and "openai" in text):
        return ("your OpenAI account has no API credit. Add credit at "
                "https://platform.openai.com/settings/organization/billing and try again.")
    if "credit balance is too low" in text:
        return ("your Anthropic account has no API credit. Add credit at "
                "https://console.anthropic.com/settings/billing and try again.")
    if "per day" in text or "perday" in text:
        return "the model's daily free quota is used up. Try tomorrow or switch LLM_MODEL in .env."
    if "429" in text or "rate limit" in text or "resource_exhausted" in text:
        return "rate limit hit. Wait a minute, or lower MAX_RPM in .env."
    if "401" in text or "authentication" in text or "api key" in text or "api_key" in text:
        return "the API key was rejected. Check the key in .env."
    if "404" in text or "not_found" in text or "no longer available" in text:
        return "the model in LLM_MODEL is not available. Pick another one in .env."
    return f"{type(exc).__name__}: {str(exc)[:300]}"
