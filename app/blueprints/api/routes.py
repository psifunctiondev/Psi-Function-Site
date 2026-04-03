import time
from collections import defaultdict

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.services.ai.client import AIClient

api_bp = Blueprint('api', __name__)

# Simple in-memory rate limiter (per IP)
# Production should use Redis-backed limiting
_rate_limits = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 10  # messages per window


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request is within rate limits."""
    now = time.time()
    # Clean old entries
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


@api_bp.post('/chat')
def chat():
    """Public prospect chat endpoint (no auth required).

    Rate-limited per IP. Accepts:
        { "prompt": "...", "history": [...] }
    Returns:
        { "reply": "..." }
    """
    ip = request.remote_addr or 'unknown'
    if not _check_rate_limit(ip):
        return jsonify({
            'reply': (
                "You're sending messages pretty quickly — let's slow down a bit. "
                "Try again in a minute, or email us at info@psifunction.com."
            )
        }), 429

    payload = request.get_json(silent=True) or {}
    prompt = payload.get('prompt', '')
    history = payload.get('history', [])

    client = AIClient()
    reply = client.send_message(prompt, history=history)
    return jsonify({'reply': reply})


@api_bp.get('/graph')
@login_required
def graph():
    return jsonify({
        'nodes': [{'id': 'welcome', 'label': 'Welcome'}],
        'edges': []
    })
