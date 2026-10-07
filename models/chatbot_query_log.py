from datetime import datetime

from application import db


class ChatbotQueryLog(db.Model):
    __tablename__ = "chatbot_query_logs"

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(300), nullable=False)
    theme = db.Column(db.String(32), nullable=False, default="unknown", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<ChatbotQueryLog id={self.id} theme={self.theme}>"
