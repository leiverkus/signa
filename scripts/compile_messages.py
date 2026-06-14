#!/usr/bin/env python3
"""Compile gettext .po files to .mo — pure Python, no msgfmt binary needed.

Usage:
    python3 scripts/compile_messages.py [LOCALE_DIR]
    # default LOCALE_DIR: signa/locale

Walks LOCALE_DIR for *.po and writes a .mo next to each. The .mo writer follows
CPython's Tools/i18n/msgfmt.py (sorted keys, no hash table — gettext does a
binary search over the sorted key table). Plurals (msgid_plural) are not
supported; the plugin doesn't use them.

Used by build-plugin.sh so the release zip always contains fresh catalogs, and
by tests/test_translations.py.
"""

import array
import os
import struct
import sys

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def parse_po(path):
    """Parse a .po file into {msgid: msgstr}. Includes the '' metadata entry."""
    messages = {}
    msgid = msgstr = None
    section = None  # 'id' | 'str'

    def flush():
        nonlocal msgid, msgstr, section
        if msgid is not None and msgstr is not None and msgstr != '':
            messages[msgid] = msgstr
        elif msgid == '' and msgstr is not None:
            messages[''] = msgstr
        msgid = msgstr = None
        section = None

    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('msgid '):
                if section == 'str':
                    flush()
                section = 'id'
                msgid = _unescape(line[6:].strip().strip('"'))
            elif line.startswith('msgstr '):
                section = 'str'
                msgstr = _unescape(line[7:].strip().strip('"'))
            elif line.startswith('"'):
                chunk = _unescape(line.strip().strip('"'))
                if section == 'id':
                    msgid = (msgid or '') + chunk
                elif section == 'str':
                    msgstr = (msgstr or '') + chunk
    if section == 'str':
        flush()
    return messages


def write_mo(messages, path):
    """Write {msgid: msgstr} as a .mo file (msgfmt.py layout)."""
    encoded = {k.encode('utf-8'): v.encode('utf-8') for k, v in messages.items()}
    keys = sorted(encoded.keys())
    offsets = []
    ids = strs = b''
    for k in keys:
        v = encoded[k]
        offsets.append((len(ids), len(k), len(strs), len(v)))
        ids += k + b'\x00'
        strs += v + b'\x00'

    n = len(keys)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]

    out = struct.pack('Iiiiiii',
                      0x950412de,        # magic
                      0,                 # version
                      n,                 # number of entries
                      7 * 4,             # start of key index
                      7 * 4 + n * 8,     # start of value index
                      0, 0)              # hash table size/offset (none)
    out += array.array('i', koffsets + voffsets).tobytes()
    out += ids + strs
    with open(path, 'wb') as f:
        f.write(out)


def main(locale_dir):
    compiled = 0
    for root, _dirs, files in os.walk(locale_dir):
        for name in files:
            if not name.endswith('.po'):
                continue
            po = os.path.join(root, name)
            mo = po[:-3] + '.mo'
            messages = parse_po(po)
            if not messages:
                print('warning: no messages in {}'.format(po), file=sys.stderr)
                continue
            write_mo(messages, mo)
            print('compiled {} -> {} ({} messages)'.format(
                po, mo, len([k for k in messages if k])))
            compiled += 1
    if compiled == 0:
        print('error: no .po files found under {}'.format(locale_dir), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    default = os.path.join(here, '..', 'signa', 'locale')
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
