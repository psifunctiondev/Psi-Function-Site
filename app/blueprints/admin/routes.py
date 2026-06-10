"""Admin blueprint — system-wide authoring for WorkItems + taxonomy use.

Routes:
  GET  /admin/                  -> redirect to /admin/work-items/
  GET  /admin/work-items/       -> list view
  GET  /admin/work-items/new/   -> create form
  POST /admin/work-items/new/   -> create submit
  GET  /admin/work-items/<id>/edit/ -> edit form
  POST /admin/work-items/<id>/edit/ -> edit submit
  POST /admin/work-items/<id>/delete/ -> delete
  POST /admin/work-items/<id>/toggle-visible/ -> quick-toggle visibility

All routes require an authenticated admin user. The blueprint is
mounted at ``/admin`` (see ``app/__init__.py``).
"""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.exceptions import Forbidden, NotFound

from app.blueprints.admin.forms import (
    AXIS_LABELS,
    WorkItemForm,
    serialize_work_item,
    tags_grouped_by_axis,
)
from app.extensions import db
from app.models.client import Client
from app.models.taxonomy import AXES, TaxonomyTag, WorkItem

admin_bp = Blueprint('admin', __name__)


# ----------------------------------------------------------------------
# Access control
# ----------------------------------------------------------------------
def _require_admin() -> None:
    """Raise 403 if the current user is not an admin."""
    if not current_user.is_authenticated or not current_user.is_admin:
        raise Forbidden()


# ----------------------------------------------------------------------
# Index
# ----------------------------------------------------------------------
@admin_bp.get('/')
@login_required
def index():
    """Landing page for the admin area — list of authoring sections."""
    _require_admin()
    return redirect(url_for('admin.work_items_list'))


# ----------------------------------------------------------------------
# WorkItem list
# ----------------------------------------------------------------------
@admin_bp.get('/work-items/')
@login_required
def work_items_list():
    _require_admin()
    items = (
        WorkItem.query
        .order_by(WorkItem.sort_order, WorkItem.id)
        .all()
    )
    rows = [serialize_work_item(i) for i in items]
    return render_template(
        'admin/work_items_list.html',
        rows=rows,
        item_count=len(rows),
    )


# ----------------------------------------------------------------------
# WorkItem create
# ----------------------------------------------------------------------
@admin_bp.route('/work-items/new/', methods=['GET', 'POST'])
@login_required
def work_item_new():
    _require_admin()
    return _render_form(item=None)


@admin_bp.route('/work-items/<int:item_id>/edit/', methods=['GET', 'POST'])
@login_required
def work_item_edit(item_id: int):
    _require_admin()
    item = WorkItem.query.get(item_id)
    if not item:
        raise NotFound()
    return _render_form(item=item)


@admin_bp.post('/work-items/<int:item_id>/delete/')
@login_required
def work_item_delete(item_id: int):
    _require_admin()
    item = WorkItem.query.get(item_id)
    if not item:
        raise NotFound()
    title = item.title
    db.session.delete(item)
    db.session.commit()
    flash(f'Deleted work item "{title}".', 'success')
    return redirect(url_for('admin.work_items_list'))


@admin_bp.post('/work-items/<int:item_id>/toggle-visible/')
@login_required
def work_item_toggle_visible(item_id: int):
    _require_admin()
    item = WorkItem.query.get(item_id)
    if not item:
        raise NotFound()
    item.is_visible = not item.is_visible
    db.session.commit()
    state = 'visible' if item.is_visible else 'hidden'
    flash(f'"{item.title}" is now {state}.', 'success')
    return redirect(url_for('admin.work_items_list'))


# ----------------------------------------------------------------------
# Shared form rendering / submission
# ----------------------------------------------------------------------
def _render_form(item: WorkItem | None):
    """Render the create/edit form, handling POST submission."""
    clients = (
        Client.query
        .order_by(Client.name)
        .all()
    )
    grouped_tags = tags_grouped_by_axis()
    form = WorkItemForm(request.form if request.method == 'POST' else None)
    is_edit = item is not None

    if request.method == 'POST':
        if not form.validate():
            for field, errors in form.errors.items():
                for msg in errors:
                    flash(f'{field}: {msg}', 'error')
        else:
            data = form.cleaned_data
            if item is None:
                item = WorkItem()
            item.title = data['title']
            item.description = data['description']
            item.client_id = data['client_id']
            item.is_projected = data['is_projected']
            item.is_visible = data['is_visible']
            item.sort_order = data['sort_order']
            item.tags = TaxonomyTag.query.filter(
                TaxonomyTag.id.in_(data['tag_ids']),
            ).all() if data['tag_ids'] else []
            if is_edit:
                db.session.commit()
                flash(f'Updated work item "{item.title}".', 'success')
            else:
                db.session.add(item)
                db.session.commit()
                flash(f'Created work item "{item.title}".', 'success')
            return redirect(url_for('admin.work_items_list'))

    return render_template(
        'admin/work_item_form.html',
        item=item,
        is_edit=is_edit,
        clients=clients,
        grouped_tags=grouped_tags,
        axes=AXES,
        axis_labels=AXIS_LABELS,
        form=form,
    )
