"""Unit tests for the pure helpers in scripts/findgcp-singlepass.py.

The networked parts need a live WebODM (covered by docs/manual-test.md); here we
just guard the fiddly multipart encoder and the image globbing.
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "findgcp-singlepass.py")


def _load():
    spec = importlib.util.spec_from_file_location("singlepass", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()


def test_encode_multipart_fields_and_file():
    ctype, body = sp._encode_multipart(
        {"epsg": "28191", "adjust": "true"},
        [("coords", "gcp_coords.txt", b"0 1 2 3\n")])
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1]
    assert isinstance(body, bytes)
    text = body.decode("utf-8")
    # boundary present and closed
    assert text.count("--" + boundary) >= 3            # 2 parts + closing
    assert text.rstrip().endswith("--" + boundary + "--")
    # field + file headers
    assert 'name="epsg"' in text and "28191" in text
    assert 'name="coords"; filename="gcp_coords.txt"' in text
    assert "Content-Type: text/plain" in text
    assert "0 1 2 3" in text


def test_encode_multipart_empty():
    ctype, body = sp._encode_multipart({}, [])
    boundary = ctype.split("boundary=", 1)[1]
    assert body.decode("utf-8").strip() == "--{}--".format(boundary)


def test_find_images_directory(tmp_path):
    for name in ["b.JPG", "a.jpg", "c.PNG", "notes.txt", "d.tif"]:
        (tmp_path / name).write_bytes(b"x")
    found = [os.path.basename(p) for p in sp.find_images(str(tmp_path))]
    # images only, sorted, case-insensitive extensions; .txt excluded
    assert found == ["a.jpg", "b.JPG", "c.PNG", "d.tif"]


def test_find_images_glob(tmp_path):
    (tmp_path / "x1.JPG").write_bytes(b"x")
    (tmp_path / "x2.JPG").write_bytes(b"x")
    found = sp.find_images(str(tmp_path / "*.JPG"))
    assert len(found) == 2
