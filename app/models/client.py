"""Client and client-resource models for the portal."""

from app.extensions import db


class Client(db.Model):
    """A Psi Function client organization."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    logo_url = db.Column(db.String(512))
    primary_color = db.Column(db.String(7))  # Hex color, e.g. #2B4C6F
    accent_color = db.Column(db.String(7))   # Hex color, e.g. #C4956A
    banner_url = db.Column(db.String(512))    # Optional hero/banner image
    tagline = db.Column(db.String(255))
    font_url = db.Column(db.String(512))  # e.g. Google Fonts CSS link
    font_display = db.Column(db.String(128))  # e.g. 'Julius Sans One, sans-serif'
    logo_max_width = db.Column(db.String(32))   # CSS value, e.g. '25rem'. None = use default.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    users = db.relationship('User', back_populates='client', lazy='dynamic')
    resources = db.relationship('ClientResource', back_populates='client', lazy='dynamic')

    def __repr__(self):
        return f'<Client {self.slug}>'


class ClientResource(db.Model):
    """A file or link shared with a specific client via the portal."""

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(64), nullable=False, default='general')
    # See the CATEGORIES dict below for the canonical list of labels.
    file_path = db.Column(db.String(512))  # For uploaded files
    external_url = db.Column(db.String(512))  # For links (e.g., OpenProject)
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # Relationships
    client = db.relationship('Client', back_populates='resources')

    CATEGORIES = {
        'proposal': 'Documents',
        'backlog': 'Project Backlog',
        'guide': 'User Guides',
        'asset': 'Assets & Deliverables',
        'invoice': 'Invoices',
        'custom': 'Custom Tools',
        'general': 'General',
        # Showcase / engagement-narrative categories. Used by the ACME
        # demo client to surface the Psi Function service arc; available
        # for any client portal that wants the same framing.
        'engagement': 'Engagement & Process',
        'deliverables': 'Deliverables',
        'tools': 'Tools & Dashboards',
    }

    @property
    def category_label(self):
        return self.CATEGORIES.get(self.category, self.category.title())

    def __repr__(self):
        return f'<ClientResource {self.title} ({self.category})>'
