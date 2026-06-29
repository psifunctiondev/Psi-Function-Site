from flask import Blueprint, Response, render_template

from app.models.taxonomy import WorkItem

public_bp = Blueprint('public', __name__)

@public_bp.get('/')
@public_bp.get('/home')
def home():
    work_items = (
        WorkItem.query
        .filter_by(is_visible=True)
        .order_by(WorkItem.sort_order, WorkItem.id)
        .all()
    )
    return render_template('public/home.html', work_items=work_items)

@public_bp.get('/about')
def about():
    return render_template('public/about.html')

@public_bp.get('/services')
def services():
    return render_template('public/services.html')

@public_bp.get('/products')
def products():
    return render_template('public/products.html')

@public_bp.get('/contact')
def contact():
    return render_template('public/contact.html')


@public_bp.get('/robots.txt')
def robots():
    return Response(
        "User-agent: *\nDisallow: /p/\nDisallow: /portal/\nDisallow: /auth/\n",
        mimetype='text/plain',
    )
