"""Taxonomy and work-showcase models.

The taxonomy is a SHARED, axis-based tagging vocabulary used to describe
client engagements and (in future) zeitgeist articles and prospect-chat
framing. Three axes:

  - vertical    -> industry / client business focus
  - function    -> business function or area improved
  - technology  -> enabling technology Psi Function deploys

``TaxonomyTag`` is intentionally generic so other taggable content types
(e.g. a future ``ZeitgeistArticle``) can share the same vocabulary via
their own association tables. ``WorkItem`` is the home-page showcase
("chyron") entity; it joins to tags through ``work_item_tags``.
"""

from app.extensions import db

# Canonical axis identifiers. Kept here so models, CLI seeders, and
# templates reference one source of truth.
AXIS_VERTICAL = 'vertical'
AXIS_FUNCTION = 'function'
AXIS_TECHNOLOGY = 'technology'
AXES = (AXIS_VERTICAL, AXIS_FUNCTION, AXIS_TECHNOLOGY)


# Many-to-many: WorkItem <-> TaxonomyTag
work_item_tags = db.Table(
    'work_item_tags',
    db.Column(
        'work_item_id',
        db.Integer,
        db.ForeignKey('work_item.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    db.Column(
        'taxonomy_tag_id',
        db.Integer,
        db.ForeignKey('taxonomy_tag.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)


class TaxonomyTag(db.Model):
    """A single tag on one of the three taxonomy axes.

    Shared vocabulary — not chyron-specific. ``slug`` is the stable,
    unique identifier (deterministic from the label); ``axis`` groups
    tags for colour-coding and filtering.
    """

    __tablename__ = 'taxonomy_tag'

    id = db.Column(db.Integer, primary_key=True)
    axis = db.Column(db.String(32), nullable=False, index=True)
    label = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    def __repr__(self):
        return f'<TaxonomyTag {self.axis}:{self.slug}>'


class WorkItem(db.Model):
    """A case study / work item shown in the home-page showcase.

    ``description`` is intended to be 2-4 sentences. ``client_id`` is
    nullable so anonymized or projected work can be represented without
    a real client row. ``is_projected`` distinguishes work actually done
    (False) from projected possibilities offered to prospects (True).
    """

    __tablename__ = 'work_item'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    client_id = db.Column(
        db.Integer, db.ForeignKey('client.id'), nullable=True,
    )
    is_projected = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=db.func.now(),
    )

    # Relationships
    client = db.relationship('Client')
    tags = db.relationship(
        'TaxonomyTag',
        secondary=work_item_tags,
        order_by='TaxonomyTag.sort_order',
        backref=db.backref('work_items', lazy='dynamic'),
    )

    def tags_by_axis(self):
        """Return tags grouped by axis, in canonical axis order.

        Returns a list of ``(axis, [tags])`` tuples so templates can
        render axis-grouped, colour-coded pill rows deterministically.
        """
        grouped = {axis: [] for axis in AXES}
        for tag in self.tags:
            grouped.setdefault(tag.axis, []).append(tag)
        return [(axis, grouped[axis]) for axis in AXES if grouped.get(axis)]

    def __repr__(self):
        return f'<WorkItem {self.title!r}>'
