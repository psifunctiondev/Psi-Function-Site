from flask import Blueprint, redirect, render_template, url_for

public_bp = Blueprint('public', __name__)

@public_bp.get('/')
def index():
    return redirect(url_for('public.home'))

@public_bp.get('/home')
def home():
    return render_template('public/home.html')

@public_bp.get('/about')
def about():
    return render_template('public/about.html')

@public_bp.get('/services')
def services():
    return render_template('public/services.html')

@public_bp.get('/contact')
def contact():
    return render_template('public/contact.html')
