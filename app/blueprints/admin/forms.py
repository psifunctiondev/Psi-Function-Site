"""Forms for the admin WorkItem authoring pages.

Hand-rolled form objects (no Flask-WTF WTForms dependency) that:
  - validate input server-side,
  - expose ``process`` helpers that accept a Werkzeug ``MultiDict`` from
    ``request.form`` and return a dict of cleaned values, and
  - integrate with the existing CSRF posture (the project does not call
    ``CSRFProtect.init_app``; CSRF is disabled in tests via
    ``WTF_CSRF_ENABLED=False`` in :class:`PytestConfig`).

We keep validation here rather than in the route so both the create and
edit paths share one source of truth and the test suite can exercise
validation rules without an HTTP round trip.
"""

from __future__ import annotations

from typing import Any

from app.models.client import Client
from app.models.taxonomy import AXES, WorkItem

# Friendly axis labels for the grouped multi-select UI. Mirrors
# ``work_chyron.html``'s axis labeling.
AXIS_LABELS = {
    'vertical': 'Industry Vertical',
    'function': 'Business Function',
    'technology': 'Enabling Technology',
}

# Reasonable cap on description length. The spec says "2-4 sentences"
# so we treat anything over ~2000 chars as a likely mistake, not a
# hard error.
DESCRIPTION_MAX_LEN = 2000
TITLE_MAX_LEN = 255


class WorkItemFormError(ValueError):
    """Raised when form validation fails.

    Carries a ``field -> [errors]`` dict so the route can surface them
    next to the relevant inputs.
    """

    def __init__(self, errors: dict[str, list[str]]):
        super().__init__('WorkItem form validation failed')
        self.errors = errors


class WorkItemForm:
    """Validate and clean input for a WorkItem create/edit submission.

    Usage::

        form = WorkItemForm(request.form)
        if not form.validate():
            # form.errors is populated
            ...
        cleaned = form.cleaned_data  # dict
    """

    def __init__(self, formdata: Any):
        # Accept either a Werkzeug ``MultiDict`` (``request.form``) or a
        # plain dict. We use ``getlist`` to handle multi-valued checkboxes.
        self._formdata = formdata
        self.errors: dict[str, list[str]] = {}
        self.cleaned_data: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate(self) -> bool:
        """Validate and populate ``cleaned_data`` / ``errors``.

        Returns True on success, False otherwise. Never raises —
        callers can branch on the boolean.
        """
        self.errors = {}
        self.cleaned_data = {}

        title = self._str_field('title', required=True, max_len=TITLE_MAX_LEN)
        description = self._str_field(
            'description', required=True, max_len=DESCRIPTION_MAX_LEN,
        )
        client_id = self._optional_int_field('client_id')
        is_projected = self._bool_field('is_projected')
        is_visible = self._bool_field('is_visible', default=True)
        sort_order = self._int_field('sort_order', default=0)

        tag_ids = self._tag_ids()

        if not self.errors:
            self.cleaned_data = {
                'title': title,
                'description': description,
                'client_id': client_id,
                'is_projected': is_projected,
                'is_visible': is_visible,
                'sort_order': sort_order,
                'tag_ids': tag_ids,
            }
        return not self.errors

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------
    def _str_field(
        self, name: str, *, required: bool, max_len: int,
    ) -> str | None:
        raw = self._formdata.get(name, '') if self._formdata else ''
        value = (raw or '').strip() if isinstance(raw, str) else ''
        if required and not value:
            self._add_error(name, 'This field is required.')
            return None
        if value and len(value) > max_len:
            self._add_error(
                name, f'Must be {max_len} characters or fewer.',
            )
            return None
        return value or None

    def _int_field(self, name: str, *, default: int) -> int:
        raw = self._formdata.get(name, '') if self._formdata else ''
        if raw in (None, ''):
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            self._add_error(name, 'Must be a whole number.')
            return default

    def _optional_int_field(self, name: str) -> int | None:
        raw = self._formdata.get(name, '') if self._formdata else ''
        if raw in (None, ''):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            self._add_error(name, 'Must be a whole number.')
            return None
        # Verify the client actually exists. We import here to avoid a
        # circular import between forms.py and the model registry.
        if not Client.query.get(value):
            self._add_error(name, 'Selected client does not exist.')
            return None
        return value

    def _bool_field(self, name: str, *, default: bool = False) -> bool:
        raw = self._formdata.get(name, '') if self._formdata else ''
        # HTML checkboxes: present (any string) means checked.
        return True if raw else default

    def _tag_ids(self) -> list[int]:
        """Collect and validate selected TaxonomyTag ids.

        Multi-valued checkboxes are submitted as repeated form keys; we
        use ``getlist`` so all selected ids are captured. Unknown ids
        (e.g. tampered request) are dropped and reported.
        """
        if not self._formdata:
            return []
        try:
            raw_list = self._formdata.getlist('tag_ids')
        except AttributeError:
            raw_list = self._formdata.get('tag_ids', '')  # type: ignore[union-attr]
        ids: list[int] = []
        unknown = 0
        for raw in raw_list:
            try:
                tag_id = int(raw)
            except (TypeError, ValueError):
                unknown += 1
                continue
            # Lazy import: defer until the model registry is fully
            # wired (matches how routes use the model).
            from app.models.taxonomy import TaxonomyTag
            if not TaxonomyTag.query.get(tag_id):
                unknown += 1
                continue
            ids.append(tag_id)
        if unknown:
            # Soft warning: don't block the request, just drop bad ids.
            # (We do add an error key so tests can assert on it.)
            self._add_error(
                'tag_ids',
                f'Ignored {unknown} unknown tag id(s).',
            )
        return ids

    def _add_error(self, field: str, message: str) -> None:
        self.errors.setdefault(field, []).append(message)


# ----------------------------------------------------------------------
# Display helpers
# ----------------------------------------------------------------------
def tags_grouped_by_axis() -> dict[str, list[Any]]:
    """Return a dict ``{axis: [TaxonomyTag, ...]}`` for the form template.

    Tags are returned in ``sort_order, label`` order so the UI is
    deterministic. Empty axes (no tags seeded) are included with an
    empty list so the template can still render the section.
    """
    from app.models.taxonomy import TaxonomyTag

    out: dict[str, list[Any]] = {axis: [] for axis in AXES}
    tags = (
        TaxonomyTag.query
        .order_by(TaxonomyTag.axis, TaxonomyTag.sort_order, TaxonomyTag.label)
        .all()
    )
    for tag in tags:
        if tag.axis in out:
            out[tag.axis].append(tag)
    return out


def serialize_work_item(item: WorkItem) -> dict[str, Any]:
    """Convert a WorkItem into a dict the form template can render.

    Centralises the field projection so list, edit, and (future)
    preview templates agree on what they show.
    """
    return {
        'id': item.id,
        'title': item.title,
        'description': item.description,
        'client_id': item.client_id,
        'is_projected': item.is_projected,
        'is_visible': item.is_visible,
        'sort_order': item.sort_order,
        'tag_ids': sorted(t.id for t in item.tags),
        'tag_count': len(item.tags),
    }


def active_tag_ids(item: WorkItem) -> set[int]:
    """Return the set of selected tag ids for an existing WorkItem."""
    return {t.id for t in item.tags}
