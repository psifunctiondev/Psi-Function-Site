from flask import Blueprint, render_template

public_bp = Blueprint('public', __name__)

@public_bp.get('/')
def home():
    return render_template('public/home.html')

@public_bp.get('/about')
def about():
    return render_template('public/about.html')
