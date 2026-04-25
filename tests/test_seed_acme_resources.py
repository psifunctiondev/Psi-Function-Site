"""Tests for `flask client seed-acme-resources` + new resource categories.

The seeder must:
  * create the ACME client row if missing (via BRANDING_PROFILES),
  * insert every ACME_DEMO_RESOURCES entry on first run,
  * be idempotent on re-run (no duplicates, no spurious updates),
  * sync changed fields back to the seed payload on re-run.

Also pins down the expanded CATEGORIES dict so the showcase narrative
keys (engagement / deliverables / tools) don't get silently dropped.
"""

from click.testing import CliRunner

from app.cli import ACME_DEMO_RESOURCES, client_cli
from app.models.client import Client, ClientResource


def _invoke(app, args):
    runner = CliRunner()
    with app.app_context():
        return runner.invoke(client_cli, args)


class TestResourceCategories:

    def test_showcase_categories_present(self):
        """The new showcase categories are in the CATEGORIES dict."""
        for key in ('engagement', 'deliverables', 'tools'):
            assert key in ClientResource.CATEGORIES, f'missing: {key}'

    def test_showcase_category_labels_are_human_friendly(self):
        labels = ClientResource.CATEGORIES
        assert labels['engagement'] == 'Engagement & Process'
        assert labels['deliverables'] == 'Deliverables'
        assert labels['tools'] == 'Tools & Dashboards'

    def test_legacy_categories_preserved(self):
        """The existing categories must still be present (no breakage)."""
        for key in ('proposal', 'backlog', 'guide', 'asset',
                    'invoice', 'custom', 'general'):
            assert key in ClientResource.CATEGORIES


class TestSeedAcmeResources:

    def test_creates_all_seed_rows(self, app, db_session):
        """First run inserts every entry in ACME_DEMO_RESOURCES."""
        result = _invoke(app, ['seed-acme-resources'])

        assert result.exit_code == 0, result.output
        client = Client.query.filter_by(slug='acme').first()
        assert client is not None

        rows = ClientResource.query.filter_by(client_id=client.id).all()
        assert len(rows) == len(ACME_DEMO_RESOURCES)

        # Every seeded title is present.
        seeded_titles = {r.title for r in rows}
        expected_titles = {e['title'] for e in ACME_DEMO_RESOURCES}
        assert seeded_titles == expected_titles

    def test_only_uses_known_categories(self, app, db_session):
        """Every seeded resource has a category in the CATEGORIES dict."""
        _invoke(app, ['seed-acme-resources'])
        client = Client.query.filter_by(slug='acme').first()
        rows = ClientResource.query.filter_by(client_id=client.id).all()
        for r in rows:
            assert r.category in ClientResource.CATEGORIES, (
                f'resource {r.title!r} has unknown category {r.category!r}'
            )

    def test_is_idempotent(self, app, db_session):
        """Re-running does not duplicate rows."""
        _invoke(app, ['seed-acme-resources'])
        first_count = ClientResource.query.count()

        result = _invoke(app, ['seed-acme-resources'])
        assert result.exit_code == 0, result.output
        assert ClientResource.query.count() == first_count
        # Output reports unchanged rather than created.
        assert 'unchanged' in result.output

    def test_resyncs_drifted_fields(self, app, db_session):
        """Manually-edited rows are re-synced on next run."""
        _invoke(app, ['seed-acme-resources'])
        client = Client.query.filter_by(slug='acme').first()

        target_title = ACME_DEMO_RESOURCES[0]['title']
        row = ClientResource.query.filter_by(
            client_id=client.id, title=target_title,
        ).first()
        assert row is not None

        # Drift the description and sort order.
        row.description = 'WRONG'
        row.sort_order = 9999
        db_session.commit()

        result = _invoke(app, ['seed-acme-resources'])
        assert result.exit_code == 0, result.output

        row = ClientResource.query.filter_by(
            client_id=client.id, title=target_title,
        ).first()
        seed = next(e for e in ACME_DEMO_RESOURCES
                    if e['title'] == target_title)
        assert row.description == seed['description']
        assert row.sort_order == seed['sort_order']

    def test_creates_client_if_missing(self, app, db_session):
        """Seed-resources also creates the ACME client row when absent."""
        assert Client.query.filter_by(slug='acme').first() is None
        result = _invoke(app, ['seed-acme-resources'])
        assert result.exit_code == 0, result.output
        assert Client.query.filter_by(slug='acme').first() is not None
