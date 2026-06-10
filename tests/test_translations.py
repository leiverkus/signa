"""Translation tests: catalog completeness (drift guard) and .mo correctness.

The German catalog is hand-maintained (WebODM has no plugin makemessages), so
msgids can silently drift from the source strings. These tests fail CI when a
{% trans %} string in the templates, or a known python-side string, is missing
from the .po — and verify the pure-python .mo compiler output via stdlib
gettext.
"""

import gettext
import importlib.util
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FINDGCP = os.path.join(HERE, "..", "findgcp")
PO_PATH = os.path.join(FINDGCP, "locale", "de", "LC_MESSAGES", "django.po")
COMPILER = os.path.join(HERE, "..", "scripts", "compile_messages.py")

TRANS_RE = re.compile(r"""\{%\s*trans\s+(?:"([^"]+)"|'([^']+)')\s*%\}""")
BLOCKTRANS_RE = re.compile(r"\{%\s*blocktrans\s*%\}(.*?)\{%\s*endblocktrans\s*%\}", re.S)

# Python-side strings that must be translatable (api.py gettext + params.py
# errors looked up via _(error) at runtime).
PYTHON_MSGIDS = [
    "No GCP coordinate file uploaded.",
    "Coordinate file too large (max 5 MB).",
    "Cannot read the coordinate file.",
    "This task has no images.",
    "Result not found.",
    "Detection failed in the worker: %(err)s",
    "Find-GCP default settings saved.",
    "A valid EPSG code is required.",
    "EPSG code out of range (1024-999999).",
    "Invalid ArUco dictionary id.",
    "Unsupported ArUco dictionary id (use 0-20 or 99).",
    "Invalid detection parameters.",
    "minrate must be in the range [0.005, 1] — values below 0.005 cause "
    "excessive false positives.",
    "ignore must be in the range [0, 1).",
]


def _load_compiler():
    spec = importlib.util.spec_from_file_location("compile_messages", COMPILER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cm = _load_compiler()
PO = cm.parse_po(PO_PATH)


def _template_msgids():
    ids = set()
    for name in ("app.html", "settings.html"):
        with open(os.path.join(FINDGCP, "templates", name), encoding="utf-8") as f:
            text = f.read()
        for m in TRANS_RE.finditer(text):
            ids.add(m.group(1) or m.group(2))
        for m in BLOCKTRANS_RE.finditer(text):
            ids.add(m.group(1))
    return ids


def test_all_template_strings_have_catalog_entries():
    missing = sorted(s for s in _template_msgids()
                     if s not in PO and s not in ("Find-GCP",))  # proper noun
    assert not missing, "template strings missing from de catalog: {}".format(missing)


def test_python_strings_have_catalog_entries():
    missing = [s for s in PYTHON_MSGIDS if s not in PO]
    assert not missing, "python strings missing from de catalog: {}".format(missing)


def test_params_errors_match_catalog():
    """Every error string params.py can return must be a catalog msgid, since
    api.py translates them via _(error) at runtime."""
    spec = importlib.util.spec_from_file_location(
        "findgcp_params", os.path.join(FINDGCP, "params.py"))
    params = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(params)

    probes = [
        {},                                            # missing epsg
        {"epsg": "abc"},
        {"epsg": "5"},
        {"epsg": "28191", "dict": "x"},
        {"epsg": "28191", "dict": "50"},
        {"epsg": "28191", "minrate": "x"},
        {"epsg": "28191", "minrate": "0"},
        {"epsg": "28191", "ignore": "1.0"},
    ]
    for data in probes:
        _p, err = params.validate_params(data)
        assert err is not None
        assert err in PO, "params error not in de catalog: {!r}".format(err)


def test_mo_compiles_and_translates(tmp_path):
    messages = cm.parse_po(PO_PATH)
    mo_path = str(tmp_path / "django.mo")
    cm.write_mo(messages, mo_path)
    with open(mo_path, "rb") as f:
        t = gettext.GNUTranslations(f)
    assert t.gettext("Detect GCPs") == "GCPs erkennen"
    assert t.gettext("Result not found.") == "Ergebnis nicht gefunden."
    assert t.gettext("Save defaults") == "Standardwerte speichern"
    # untranslated strings pass through unchanged
    assert t.gettext("not in catalog") == "not in catalog"


def test_shipped_mo_is_up_to_date():
    """The committed .mo must match the .po (build-plugin.sh recompiles, but a
    stale committed .mo would still ship in dev checkouts)."""
    mo_path = PO_PATH[:-3] + ".mo"
    assert os.path.isfile(mo_path), "django.mo missing — run scripts/compile_messages.py"
    with open(mo_path, "rb") as f:
        t = gettext.GNUTranslations(f)
    for msgid, msgstr in PO.items():
        if not msgid:
            continue
        assert t.gettext(msgid) == msgstr, "stale django.mo for {!r}".format(msgid)
