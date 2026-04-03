"""Article model for the Zeitgeist curated news feed."""

from app.extensions import db

# Many-to-many association table for article ↔ tag
article_tags = db.Table(
    'article_tags',
    db.Column('article_id', db.Integer, db.ForeignKey('article.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True),
)


class Tag(db.Model):
    """A filterable tag — business function, industry, or technology."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    category = db.Column(db.String(32), nullable=False)
    # Categories: 'function' (business function), 'industry', 'technology'

    CATEGORIES = {
        'function': 'Business Function',
        'industry': 'Industry',
        'technology': 'Technology',
    }

    @property
    def category_label(self):
        return self.CATEGORIES.get(self.category, self.category.title())

    def __repr__(self):
        return f'<Tag {self.slug} ({self.category})>'


class Article(db.Model):
    """A curated news article or thought piece."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(512), nullable=False)
    url = db.Column(db.String(1024), nullable=False)
    source = db.Column(db.String(255))  # Publication name
    summary = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(1024))
    published_at = db.Column(db.DateTime)
    curated_at = db.Column(db.DateTime, server_default=db.func.now())
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    tags = db.relationship('Tag', secondary=article_tags, backref='articles', lazy='joined')

    def __repr__(self):
        return f'<Article {self.title[:40]}>'
