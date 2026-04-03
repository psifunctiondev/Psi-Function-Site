from flask import Blueprint, render_template, request

from app.models.article import Article, Tag

zeitgeist_bp = Blueprint('zeitgeist', __name__)


@zeitgeist_bp.get('/zeitgeist')
def index():
    """Curated news feed with faceted tag filtering."""

    # Parse selected tag slugs from query string (?tags=ai,marketing,...)
    selected_slugs = [
        s.strip()
        for s in request.args.get('tags', '').split(',')
        if s.strip()
    ]

    # Build article query
    query = Article.query.filter_by(is_visible=True)

    if selected_slugs:
        # Filter to articles that have ALL selected tags
        for slug in selected_slugs:
            query = query.filter(Article.tags.any(Tag.slug == slug))

    articles = query.order_by(Article.curated_at.desc()).limit(50).all()

    # All tags grouped by category for the filter sidebar
    all_tags = Tag.query.order_by(Tag.category, Tag.name).all()
    tags_by_category = {}
    for tag in all_tags:
        tags_by_category.setdefault(tag.category, []).append(tag)

    return render_template(
        'public/zeitgeist.html',
        articles=articles,
        tags_by_category=tags_by_category,
        tag_categories=Tag.CATEGORIES,
        selected_slugs=selected_slugs,
    )
