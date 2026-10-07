import re

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

public_bp = Blueprint("public", __name__, template_folder="../templates")


FAQ_RESPONSES = [
    {
        "keywords": ["timing", "timings", "hours", "open", "closing", "opening", "time", "kab khula", "kab band"],
        "answer": "Our timings are Monday to Sunday, 07:00 AM to 10:00 PM IST.",
    },
    {
        "keywords": ["address", "location", "where", "map", "kaha", "kahaan", "jagah"],
        "answer": "We are at Prerna Library, Pandurang Building, Mahsul Colony, near Govt. ITI College, behind Akola Bus Stand, Akola 444001.",
    },
    {
        "keywords": ["contact", "phone", "call", "number", "email", "mobile", "whatsapp"],
        "answer": "You can call us at 8459106039 or email prernalab705@gmail.com.",
    },
    {
        "keywords": ["amenities", "facility", "facilities", "wifi", "parking", "water", "toilet", "lamp", "charging", "cctv"],
        "answer": "Amenities include free Wi-Fi, parking, purified and cold water, charging points, personal lamps, CCTV, and separate toilets.",
    },
    {
        "keywords": ["seat", "reserve", "reservation", "booking", "book", "availability", "available", "khali seat"],
        "answer": "For seat reservation and availability, please call 8459106039 or use the Contact page. We will help you with the next steps.",
    },
    {
        "keywords": ["fee", "fees", "price", "cost", "plan", "membership", "charges", "monthly"],
        "answer": "Membership fees depend on plan duration and seat type. Please call 8459106039 for the latest pricing.",
    },
]


def _normalize_text(value):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _chatbot_answer(message):
    normalized = _normalize_text(message)
    if not normalized:
        return "Please type your question."

    best_answer = None
    best_score = 0
    for item in FAQ_RESPONSES:
        score = sum(1 for keyword in item["keywords"] if keyword in normalized)
        if score > best_score:
            best_score = score
            best_answer = item["answer"]

    if best_score > 0 and best_answer:
        return best_answer

    return "I can help with timings, location, amenities, seat booking, and fees. For more details, call 8459106039."


@public_bp.route("/home")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("public/index.html")


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")


@public_bp.route("/chatbot/ask", methods=["POST"])
def chatbot_ask():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    return jsonify({"answer": _chatbot_answer(message)})
