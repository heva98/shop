"""Compile locale/*/LC_MESSAGES/django.po into the .mo files Django reads.

Django's own `compilemessages` needs GNU gettext's msgfmt, which Windows
machines rarely have; this does the same job in plain Python, so editing
a translation is: change the .po, run `python manage.py compile_translations`,
restart the app.
"""
import ast
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def parse_po(text):
    """{msgid: msgstr} from a .po file; plural entries are keyed
    'singular\\0plural' with their forms joined by '\\0', as in a .mo.
    Fuzzy and untranslated entries are left out."""
    entries, current, field, fuzzy = {}, {}, None, False

    def flush():
        nonlocal current, fuzzy
        msgid = current.get('msgid')
        if msgid is not None and not fuzzy:
            if 'msgid_plural' in current:
                forms = [current[k] for k in sorted(k for k in current if k.startswith('msgstr['))]
                if any(forms):
                    entries[f"{msgid}\0{current['msgid_plural']}"] = '\0'.join(forms)
            elif current.get('msgstr') or msgid == '':
                entries[msgid] = current.get('msgstr', '')
        current, fuzzy = {}, False

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            if line.startswith('#,') and 'fuzzy' in line:
                flush()
                fuzzy = True
            continue
        if line.startswith('"'):
            if field is None:
                raise CommandError(f'Line {number}: text outside an entry.')
            current[field] += ast.literal_eval(line)
            continue
        keyword, _, value = line.partition(' ')
        if keyword == 'msgid' and 'msgid' in current:
            flush()
        field = keyword
        current[field] = ast.literal_eval(value)
    flush()
    return entries


def write_mo(entries, path):
    """GNU .mo format: header, sorted original/translation tables, strings."""
    keys = sorted(entries)
    ids = [k.encode('utf-8') for k in keys]
    strs = [entries[k].encode('utf-8') for k in keys]
    count = len(keys)
    originals_at = 7 * 4
    translations_at = originals_at + count * 8
    data_at = translations_at + count * 8
    tables, blob = [[], []], b''
    for table, items in ((0, ids), (1, strs)):
        for item in items:
            tables[table].append((len(item), data_at + len(blob)))
            blob += item + b'\0'
    out = struct.pack('<7I', 0x950412de, 0, count, originals_at, translations_at, 0, 0)
    for table in tables:
        for length, offset in table:
            out += struct.pack('<2I', length, offset)
    path.write_bytes(out + blob)


class Command(BaseCommand):
    help = 'Compile the .po translation files in LOCALE_PATHS into .mo files.'

    def handle(self, *args, **options):
        found = False
        for root in settings.LOCALE_PATHS:
            for po in sorted(Path(root).glob('*/LC_MESSAGES/*.po')):
                found = True
                entries = parse_po(po.read_text(encoding='utf-8'))
                write_mo(entries, po.with_suffix('.mo'))
                self.stdout.write(f'{po}: {len(entries) - ("" in entries)} messages')
        if not found:
            raise CommandError('No .po files found under LOCALE_PATHS.')
