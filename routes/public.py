import re

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from application import db
from models import ChatbotQueryLog

public_bp = Blueprint("public", __name__, template_folder="../templates")


FAQ_RESPONSES = [
    {
        "theme": "timings",
        "keywords": ["timing", "timings", "hours", "open", "closing", "opening", "time", "kab khula", "kab band"],
        "answer": "Our timings are Monday to Sunday, 07:00 AM to 10:00 PM IST.",
    },
    {
        "theme": "location",
        "keywords": ["address", "location", "where", "map", "kaha", "kahaan", "jagah"],
        "answer": "We are at Prerna Library, Pandurang Building, Mahsul Colony, near Govt. ITI College, behind Akola Bus Stand, Akola 444001.",
    },
    {
        "theme": "contact",
        "keywords": ["contact", "phone", "call", "number", "email", "mobile", "whatsapp"],
        "answer": "You can call us at 8799954976 or email prernalab705@gmail.com.",
    },
    {
        "theme": "amenities",
        "keywords": ["amenities", "facility", "facilities", "wifi", "parking", "water", "toilet", "lamp", "charging", "cctv"],
        "answer": "Amenities include free Wi-Fi, parking, purified and cold water, charging points, personal lamps, CCTV, and gender separate toilets.",
    },
    {
        "theme": "booking",
        "keywords": ["seat", "reserve", "reservation", "booking", "book", "availability", "available", "khali seat"],
        "answer": "For seat reservation and availability, please call 8459106039 or use the Contact page. We will help you with the next steps.",
    },
    {
        "theme": "fees",
        "keywords": ["fee", "fees", "price", "cost", "plan", "membership", "charges", "monthly"],
        "answer": "Monthly Fees:- Reserved seat = 700 Rs and Unreserved Seat = 500 Rs",
    },
]


def _normalize_text(value):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _chatbot_answer(message):
    normalized = _normalize_text(message)
    if not normalized:
        return "Please type your question.", "unknown"

    best_answer = None
    best_theme = "unknown"
    best_score = 0
    for item in FAQ_RESPONSES:
        score = sum(1 for keyword in item["keywords"] if keyword in normalized)
        if score > best_score:
            best_score = score
            best_answer = item["answer"]
            best_theme = item["theme"]

    if best_score > 0 and best_answer:
        return best_answer, best_theme

    return "I can help with timings, location, amenities, seat booking, and fees. For more details, call 8459106039.", "unknown"


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
    answer, theme = _chatbot_answer(message)

    if message:
        try:
            db.session.add(
                ChatbotQueryLog(
                    message=message[:300],
                    theme=theme,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({"answer": answer})


@public_bp.route("/chatbot/stats", methods=["GET"])
@login_required
def chatbot_stats():
    if not current_user.is_admin:
        abort(403)

    total_questions = db.session.query(func.count(ChatbotQueryLog.id)).scalar() or 0

    theme_counts_rows = (
        db.session.query(ChatbotQueryLog.theme, func.count(ChatbotQueryLog.id))
        .group_by(ChatbotQueryLog.theme)
        .order_by(func.count(ChatbotQueryLog.id).desc())
        .all()
    )
    theme_counts = {theme or "unknown": count for theme, count in theme_counts_rows}

    daily_rows = (
        db.session.query(
            func.date(ChatbotQueryLog.created_at).label("day"),
            func.count(ChatbotQueryLog.id).label("count"),
        )
        .group_by(func.date(ChatbotQueryLog.created_at))
        .order_by(func.date(ChatbotQueryLog.created_at).desc())
        .limit(7)
        .all()
    )

    daily_trend = [
        {"date": str(row.day), "count": row.count}
        for row in reversed(daily_rows)
    ]

    return jsonify(
        {
            "total_questions": total_questions,
            "theme_counts": theme_counts,
            "daily_trend": daily_trend,
        }
    )
