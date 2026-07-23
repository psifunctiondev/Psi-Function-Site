from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

"""
Slides client — wraps the Google Slides + Drive API calls needed by
``DriveSaveStrategy``.

Two responsibilities:

1. **Auth** — mint an OAuth bearer token via JWT grant using a service
   account key. The token is cached in-process and refreshed ~5min
   before expiry. Service account impersonates a workspace user
   (``subject=``) so the resulting presentation is owned by that user,
   not by the service account.

2. **Wire translation** — the renderer emits a brand-intent JSON
   (``render_slides_spec``); the Google Slides API wants a different
   shape. This module translates intent to wire format.

API flow for one ``save()`` call:
    1. ``POST /v1/presentations`` body=``{"title": ...}`` — note that
       only ``title`` is honored at create time; everything else is
       ignored (see api.google.com/slides/.../presentations/create).
    2. ``POST /v1/presentations/{id}:batchUpdate`` body=
       ``{"requests": [...CreateSlide + InsertText...]}`` — actually
       inserts the slides + their text elements.
    3. ``PATCH /drive/v3/files/{id}?fields=id,name,webViewLink`` body=
       ``{"name": ..., "parents": [...]}`` — Drive uses ``name`` (not
       Slides' title) for the filename in the UI, and ``parents`` to
       move the file into the BrandSight Output folder.

All HTTP via ``httpx``. Auth retry handled by ``_get_access_token``.
"""


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # unix seconds


class DriveAuthError(RuntimeError):
    """Raised when token grant or impersonation fails."""


class _SlidesAuth:
    """JWT-grant access-token cache for the Slides API.

    The service account JSON holds the private key; ``subject`` is the
    workspace user to impersonate. Token expiry buffer: refresh
    ~5min before actual expiry to avoid races.
    """

    _TOKEN_EXPIRY_BUFFER_S = 300
    _SCOPE = (
        'https://www.googleapis.com/auth/presentations '
        'https://www.googleapis.com/auth/drive.file'
    )
    _TOKEN_URL = 'https://oauth2.googleapis.com/token'

    def __init__(
        self,
        service_account_json_path: Path,
        subject: str,
        *,
        _http_client: httpx.Client | None = None,
    ) -> None:
        self.service_account_json_path = Path(service_account_json_path)
        self.subject = subject
        # Allow test injection of a mock client.
        self._http = _http_client or httpx.Client(timeout=30.0)
        self._cached: _CachedToken | None = None

    def _load_sa(self) -> dict:
        with self.service_account_json_path.open('r', encoding='utf-8') as f:
            return json.load(f)

    def _mint_token(self) -> _CachedToken:
        sa = self._load_sa()
        # Lazy-import the JWT lib so the module loads even if PyJWT
        # isn't installed in a dev env (cheap failure mode).
        try:
            import jwt  # PyJWT
        except ImportError as exc:
            raise DriveAuthError(
                'PyJWT not installed; needed to sign the JWT grant '
                'from a service-account key (pip install PyJWT)'
            ) from exc

        now = int(time.time())
        assertion = jwt.encode(
            {
                'iss': sa['client_email'],
                'scope': self._SCOPE,
                'aud': self._TOKEN_URL,
                'iat': now,
                'exp': now + 3600,
                'sub': self.subject,
            },
            sa['private_key'],
            algorithm='RS256',
        )
        try:
            resp = self._http.post(
                self._TOKEN_URL,
                data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                    'assertion': assertion,
                },
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise DriveAuthError(
                f'token grant transport error: {exc}'
            ) from exc

        if resp.status_code != 200:
            raise DriveAuthError(
                f'token grant failed: HTTP {resp.status_code} '
                f'{resp.text[:500]}'
            )
        body = resp.json()
        if 'access_token' not in body:
            raise DriveAuthError(
                f'token grant response missing access_token: '
                f'{json.dumps(body)[:500]}'
            )
        return _CachedToken(
            access_token=body['access_token'],
            expires_at=now + int(body.get('expires_in', 3600)),
        )

    def access_token(self) -> str:
        now = time.time()
        if (
            self._cached is None
            or (self._cached.expires_at - self._TOKEN_EXPIRY_BUFFER_S) <= now
        ):
            self._cached = self._mint_token()
        return self._cached.access_token


# ---------------------------------------------------------------------------
# Wire translation: brand-intent -> Google Slides API
# ---------------------------------------------------------------------------


# Standard 16:9 page dimensions in EMU (English Metric Units):
#   1 inch = 914400 EMU
#   13.333" x 7.5" = 12_192_000 x 6_858_000 EMU
SLIDE_W_EMU = 12_192_000
SLIDE_H_EMU = 6_858_000

# Layout positions for our intent layouts. Tuned by hand for the MVP —
# we diff against Quinn's reference deck after the first artifact and
# adjust per §'drive save' rollback if any element lands off-canvas.
# Coordinates: (x_emu, y_emu, width_emu, height_emu) for each element.
_LAYOUT_POSITIONS = {
    'TITLE': {
        # Standard big-title slide. Title centered horizontally; subtitle
        # near vertical-center below the title.
        'TITLE': (914_400, 1_828_800, 10_363_200, 1_524_000),       # ~1" top, full-width-minus-margin, ~1.67" tall, centered horizontally  # noqa: E501
        'SUBTITLE': (914_400, 3_657_600, 10_363_200, 914_400),     # ~5" down, half-inch tall
    },
    'TITLE_AND_BODY': {
        'TITLE': (685_800, 457_200, 10_820_400, 914_400),          # ~0.75" from top, full-width
        'BODY':  (685_800, 1_600_200, 10_820_400, 4_800_000),      # ~1.75" down, fills bottom
    },
}


def _shape_request(
    object_id: str, page_object_id: str, text: str,
    x: int, y: int, w: int, h: int,
) -> dict:
    """Build a CreateShapeRequest for a single text box.

    ``page_object_id`` is the parent slide (page) the shape belongs to.
    Without it the Slides API returns 400 ``The page () could not be
    found`` — caught us on the first DriveSaveStrategy smoke
    (2026-07-21).
    """
    return {
        'createShape': {
            'objectId': object_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': page_object_id,
                'transform': {
                    'translateX': x,
                    'translateY': y,
                    'scaleX': 1,
                    'scaleY': 1,
                    'unit': 'EMU',
                },
                'size': {
                    'width': {'magnitude': w, 'unit': 'EMU'},
                    'height': {'magnitude': h, 'unit': 'EMU'},
                },
            },
        },
    }


def _insert_text_request(element_object_id: str, text: str) -> dict:
    """Build an InsertTextRequest for an existing text-box element."""
    return {
        'insertText': {
            'objectId': element_object_id,
            'insertionIndex': 0,
            'text': text,
        },
    }


def _intent_slide_to_wire_requests(slide: dict, insertion_index: int) -> list[dict]:
    """Translate one intent-spec slide into batchUpdate requests.

    Intent shape:
        {slideId: str, layout: 'TITLE' | 'TITLE_AND_BODY',
         elements: [{type: 'text', placeholder: 'TITLE' | 'SUBTITLE' | 'BODY',
                      text: str}, ...]}

    Wire shape produced:
        [
          {createSlide: {objectId, insertionIndex,
                          slideLayoutReference: {predefinedLayout}}},
          ... per-element:
          {createShape: {objectId: <element>, shapeType: TEXT_BOX,
                          elementProperties: {transform, size}}},
          {insertText: {objectId: <element>, insertionIndex: 0, text}},
        ]

    We use CreateShape + InsertText instead of inserting into layout
    placeholders because reading-back-the-slide to find placeholder
    objectIds adds a round-trip and we want one POST per save.
    Element objectIds are derived from slideId + placeholder to stay
    stable across regenerations.
    """
    layout = slide.get('layout', 'TITLE_AND_BODY')
    predefined = layout
    if layout not in _LAYOUT_POSITIONS:
        # Unknown layout — fall back to a blank title-and-body slide.
        predefined = 'TITLE_AND_BODY'
        positions = _LAYOUT_POSITIONS['TITLE_AND_BODY']
    else:
        positions = _LAYOUT_POSITIONS[layout]

    requests: list[dict] = [
        {
            'createSlide': {
                'objectId': slide['slideId'],
                'insertionIndex': insertion_index,
                'slideLayoutReference': {'predefinedLayout': predefined},
            },
        },
    ]

    for element in slide.get('elements', []):
        if element.get('type') != 'text':
            # Image / video / shape elements are out of scope for the
            # MVP; skip silently rather than raising so a renderer
            # change in the future doesn't immediately break save.
            continue
        placeholder = element.get('placeholder', 'BODY')
        text = element.get('text', '')
        element_object_id = f"{slide['slideId']}_{placeholder.lower()}"
        if placeholder in positions:
            x, y, w, h = positions[placeholder]
        else:
            # Unknown placeholder on a known layout — fall back to a
            # body-sized box near bottom of slide.
            x, y, w, h = positions.get('BODY', (685_800, 3_200_400, 10_820_400, 3_200_400))
        requests.append(_shape_request(
            element_object_id, slide['slideId'], text, x, y, w, h,
        ))
        requests.append(_insert_text_request(element_object_id, text))

    return requests


def build_batch_update_requests(slides: list[dict]) -> list[dict]:
    """Translate a list of intent-spec slides into batchUpdate requests.

    Used by ``DriveSaveStrategy.save()`` after ``presentations.create``.
    """
    requests: list[dict] = []
    for i, slide in enumerate(slides):
        requests.extend(_intent_slide_to_wire_requests(slide, insertion_index=i))
    return requests


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DriveFolderAccessError(RuntimeError):
    """Raised when the Drive folder ID isn't writable by the workspace
    user — typically a misconfiguration (folder deleted, permissions
    not granted, wrong subject). Worker treats as fatal."""


class SlidesClient:
    """Auth + API calls for ``DriveSaveStrategy``."""

    def __init__(
        self,
        service_account_json_path: Path,
        subject: str,
        *,
        _http_client: httpx.Client | None = None,
    ) -> None:
        self._http = _http_client or httpx.Client(timeout=30.0)
        self._auth = _SlidesAuth(
            service_account_json_path=service_account_json_path,
            subject=subject,
            _http_client=self._http,
        )

    # ---- auth helpers -------------------------------------------------

    def _auth_headers(self) -> dict:
        return {'Authorization': f'Bearer {self._auth.access_token()}'}

    # ---- Slides API ---------------------------------------------------

    def create_presentation(
        self, title: str, slides_spec: dict,
    ) -> str:
        """Step 1+2: create blank presentation, then batchUpdate with
        the slide content. Returns the presentation ID.

        Per Google's API: ``presentations.create`` ignores everything
        except ``title``; actual content goes in batchUpdate.
        """
        url = 'https://slides.googleapis.com/v1/presentations'
        try:
            resp = self._http.post(
                url, headers=self._auth_headers(),
                json={'title': title},
            )
        except httpx.HTTPError as exc:
            raise DriveAuthError(
                f'presentations.create transport error: {exc}'
            ) from exc
        if resp.status_code != 200:
            raise DriveAuthError(
                f'presentations.create failed: HTTP {resp.status_code} '
                f'{resp.text[:500]}'
            )
        presentation_id = resp.json()['presentationId']

        # Step 2: batchUpdate with the actual slides.
        requests = build_batch_update_requests(slides_spec.get('slides', []))
        if requests:
            update_url = (
                f'https://slides.googleapis.com/v1/presentations/'
                f'{presentation_id}:batchUpdate'
            )
            update_resp = self._http.post(
                update_url, headers=self._auth_headers(),
                json={'requests': requests},
            )
            if update_resp.status_code != 200:
                # Orphan presentation exists at this point. Surface
                # the failure with a hint so we can clean up manually.
                raise DriveAuthError(
                    f'presentations.batchUpdate failed after create '
                    f'for presentation_id={presentation_id}: '
                    f'HTTP {update_resp.status_code} '
                    f'{update_resp.text[:500]}. '
                    f'An empty presentation was created — clean up via '
                    f'the Drive UI or call files.delete.'
                )
        return presentation_id

    def move_to_folder(
        self,
        presentation_id: str,
        folder_id: str,
        name: str,
    ) -> str:
        """Step 3: PATCH Drive file to rename (Drive uses ``name``, not
        Slides' ``title``) AND move into the output folder.

        Drive v3 PATCH for parent changes uses ``addParents`` +
        ``removeParents`` *query* parameters — NOT body fields. We
        first GET the file's current parents, then PATCH with both
        lists so the file ends up only in the target folder (not also
        leaking into the impersonated user's My Drive).

        Returns the ``webViewLink`` for the file.
        """
        # Step 3a: read current parents so we can remove them.
        get_url = f'https://www.googleapis.com/drive/v3/files/{presentation_id}'
        try:
            get_resp = self._http.get(
                get_url,
                headers=self._auth_headers(),
                params={'fields': 'id,parents', 'supportsAllDrives': 'true'},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise DriveFolderAccessError(
                f'files.get (pre-move) transport error for '
                f'{presentation_id}: {exc}'
            ) from exc
        if get_resp.status_code != 200:
            raise DriveFolderAccessError(
                f'files.get (pre-move) failed: HTTP {get_resp.status_code} '
                f'{get_resp.text[:500]}'
            )
        current_parents = get_resp.json().get('parents', [])

        # Step 3b: PATCH with addParents + removeParents query params,
        # plus name + description in body.
        patch_url = (
            f'https://www.googleapis.com/drive/v3/files/{presentation_id}'
        )
        params = {
            'fields': 'id,name,webViewLink',
            'addParents': folder_id,
            'removeParents': ','.join(current_parents) if current_parents else '',
            'supportsAllDrives': 'true',
        }
        body = {
            'name': name,
            'description': (
                f'BrandSight Competitive Audit for {name} — '
                f'created by DrifterBot.'
            ),
        }
        try:
            resp = self._http.patch(
                patch_url, headers=self._auth_headers(),
                params=params, json=body,
            )
        except httpx.HTTPError as exc:
            raise DriveFolderAccessError(
                f'files.patch transport error for {presentation_id}: '
                f'{exc}'
            ) from exc
        if resp.status_code == 404:
            raise DriveFolderAccessError(
                f'files.patch 404 — folder_id={folder_id!r} not visible '
                f'to the impersonated subject. Check folder exists and '
                f'the workspace user has at least Viewer access.'
            )
        if resp.status_code == 403:
            raise DriveFolderAccessError(
                f'files.patch 403 — subject cannot modify files in '
                f'folder_id={folder_id!r}. Likely permission gap on the '
                'BrandSight Output folder or the presentation was '
                'created in a different drive than expected.'
            )
        if resp.status_code != 200:
            raise DriveFolderAccessError(
                f'files.patch failed: HTTP {resp.status_code} '
                f'{resp.text[:500]}'
            )
        return resp.json().get('webViewLink', '')

    def delete_file(
        self,
        file_id: str,
        *,
        swallow_404: bool = True,
    ) -> None:
        """Cleanup helper: delete a file from Drive via the Drive v3
        API. Used by ``DriveSaveStrategy`` to clean up orphan
        presentations left behind when ``create_presentation`` or
        ``move_to_folder`` fails partway through.

        Returns silently on 404 (file already gone) when
        ``swallow_404`` is True, since the goal is just "make sure the
        orphan is gone" and racing a second delete shouldn't fail the
        pipeline.

        Raises ``DriveAuthError`` on any other non-2xx so the caller
        can decide whether to retry.
        """
        url = f'https://www.googleapis.com/drive/v3/files/{file_id}'
        try:
            resp = self._http.delete(
                url,
                headers=self._auth_headers(),
                params={'supportsAllDrives': 'true'},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise DriveAuthError(
                f'files.delete transport error for {file_id}: {exc}'
            ) from exc
        if resp.status_code in (200, 204):
            return
        if resp.status_code == 404 and swallow_404:
            logger.warning(
                'files.delete: file_id=%s already gone (404 swallowed)',
                file_id,
            )
            return
        raise DriveAuthError(
            f'files.delete failed for {file_id}: '
            f'HTTP {resp.status_code} {resp.text[:500]}'
        )
