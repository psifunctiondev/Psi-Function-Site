"""
tests/test_taxonomy.py
Tests for the taxonomy / work-showcase models, slug generation, and
the chyron rendering on the home page.
"""

from app.cli import (
    TAXONOMY_AXES,
    WORK_DEMO_ITEMS,
    taxonomy_slug,
)
from app.models.taxonomy import AXES, TaxonomyTag, WorkItem

# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

class TestTaxonomySlug:

    def test_ampersand_becomes_and(self):
        assert taxonomy_slug('Architecture & Design') == 'architecture-and-design'

    def test_comma_dropped(self):
        assert taxonomy_slug('Compliance, Risk & Legal') == 'compliance-risk-and-legal'

    def test_hyphenated_word_preserved(self):
        assert taxonomy_slug('Retail & E-commerce') == 'retail-and-e-commerce'

    def test_lowercased(self):
        assert taxonomy_slug('Cloud Computing') == 'cloud-computing'


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestTaxonomyModels:

    def test_create_tag_and_workitem_with_tags(self, db_session):
        v = TaxonomyTag(axis='vertical', label='Architecture & Design',
                        slug='architecture-and-design', sort_order=0)
        f = TaxonomyTag(axis='function', label='Product & Service Delivery',
                        slug='product-and-service-delivery', sort_order=0)
        db_session.add_all([v, f])
        db_session.flush()

        item = WorkItem(title='Demo', description='A demo work item.')
        item.tags = [v, f]
        db_session.add(item)
        db_session.commit()

        assert item.client_id is None  # nullable client
        assert item.is_projected is False
        assert item.is_visible is True
        assert len(item.tags) == 2

    def test_tags_by_axis_groups_in_canonical_order(self, db_session):
        tech = TaxonomyTag(axis='technology', label='Data & Analytics',
                           slug='data-and-analytics', sort_order=0)
        vert = TaxonomyTag(axis='vertical', label='Health & Wellness',
                           slug='health-and-wellness', sort_order=0)
        db_session.add_all([tech, vert])
        db_session.flush()

        item = WorkItem(title='Grouping', description='x')
        item.tags = [tech, vert]
        db_session.add(item)
        db_session.commit()

        grouped = item.tags_by_axis()
        axes_present = [axis for axis, _ in grouped]
        # vertical must precede technology per canonical AXES order
        assert axes_present == ['vertical', 'technology']
        assert AXES == ('vertical', 'function', 'technology')


# ---------------------------------------------------------------------------
# Seed data integrity
# ---------------------------------------------------------------------------

class TestSeedData:

    def test_axes_have_expected_counts(self):
        assert len(TAXONOMY_AXES['vertical']) == 10
        assert len(TAXONOMY_AXES['function']) == 9
        assert len(TAXONOMY_AXES['technology']) == 8

    def test_all_slugs_unique(self):
        slugs = [
            taxonomy_slug(label)
            for labels in TAXONOMY_AXES.values()
            for label in labels
        ]
        assert len(slugs) == len(set(slugs))

    def test_demo_work_tags_reference_real_labels(self):
        all_labels = {
            label
            for labels in TAXONOMY_AXES.values()
            for label in labels
        }
        for item in WORK_DEMO_ITEMS:
            for label in item['tags']:
                assert label in all_labels, f'unknown tag label: {label}'


# ---------------------------------------------------------------------------
# Chyron rendering on the home page
# ---------------------------------------------------------------------------

class TestChyronRender:

    def test_chyron_renders_when_workitems_exist(self, client, db_session):
        tag = TaxonomyTag(axis='vertical', label='Architecture & Design',
                          slug='architecture-and-design', sort_order=0)
        db_session.add(tag)
        db_session.flush()
        item = WorkItem(title='TruRender Pipeline',
                        description='Render-to-photo.', sort_order=0)
        item.tags = [tag]
        db_session.add(item)
        db_session.commit()

        html = client.get('/').data.decode()
        assert 'work-chyron' in html
        assert 'TruRender Pipeline' in html
        assert 'work-pill--vertical' in html

    def test_chyron_absent_when_no_workitems(self, client, db_session):
        html = client.get('/').data.decode()
        assert 'work-chyron__card' not in html
