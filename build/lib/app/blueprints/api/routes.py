from flask import Blueprint, jsonify, request
from flask_login import login_required
from app.services.ai.client import AIClient

api_bp = Blueprint('api', __name__)

@api_bp.post('/chat')
@login_required
def chat():
    payload = request.get_json(silent=True) or {}
    prompt = payload.get('prompt', '')
    client = AIClient()
    return jsonify({'reply': client.send_message(prompt)})

@api_bp.get('/graph')
@login_required
def graph():
    return jsonify({
        'nodes': [{'id': 'welcome', 'label': 'Welcome'}],
        'edges': []
    })
