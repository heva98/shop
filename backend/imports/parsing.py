"""Reading an uploaded spreadsheet into rows of {column: text}.

CSV and Excel .xlsx are both supported. .xlsx is read with the standard
library (an .xlsx file is a zip of XML parts), so no extra dependency is
needed on the server; only the first worksheet is read. The old binary
.xls format is not supported — Excel's "Save as > .xlsx or CSV" fixes that.
"""

import calendar
import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

MAX_ROWS = 5000
_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


class ImportFileError(ValueError):
    """The file itself can't be read (wrong format, empty, too big)."""


class CellError(ValueError):
    """One cell's value is not usable; the message is shown against its row."""


def normalize_header(name):
    return re.sub(r'[^a-z0-9]+', '_', str(name or '').strip().lower()).strip('_')


def read_rows(upload):
    """Returns [(row_number, {normalized_header: str})], skipping blank rows.
    Row numbers match what the user sees in Excel (header is row 1)."""
    name = (getattr(upload, 'name', '') or '').lower()
    data = upload.read()
    if not data:
        raise ImportFileError('The file is empty.')
    if name.endswith('.xlsx') or data[:2] == b'PK':
        table = _read_xlsx(data)
    elif name.endswith('.xls'):
        raise ImportFileError('Old .xls files are not supported. In Excel use "Save as" and choose .xlsx or CSV.')
    else:
        table = _read_csv(data)
    if not table:
        raise ImportFileError('The file has no rows.')
    headers = [normalize_header(h) for h in table[0]]
    rows = []
    for offset, values in enumerate(table[1:], start=2):
        cells = {h: str(values[i]).strip() if i < len(values) and values[i] is not None else ''
                 for i, h in enumerate(headers) if h}
        if any(cells.values()):
            rows.append((offset, cells))
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f'The file has {len(rows)} rows; import at most {MAX_ROWS} at a time.')
    return headers, rows


def _read_csv(data):
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportFileError('Could not read the file. Save it as CSV (UTF-8) or .xlsx.')
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFileError('This is not a valid .xlsx file.')
    try:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ElementTree.fromstring(archive.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si', _NS):
                shared.append(''.join(t.text or '' for t in si.iter(f'{{{_NS["m"]}}}t')))
        sheet_path = _first_sheet_path(archive)
        root = ElementTree.fromstring(archive.read(sheet_path))
    except (KeyError, ElementTree.ParseError):
        raise ImportFileError('Could not read the first worksheet of this .xlsx file.')

    table = []
    for row in root.iter(f'{{{_NS["m"]}}}row'):
        values = {}
        for cell in row.findall('m:c', _NS):
            col = _column_index(cell.get('r', ''))
            kind = cell.get('t')
            v = cell.find('m:v', _NS)
            if kind == 's' and v is not None:
                values[col] = shared[int(v.text)]
            elif kind == 'inlineStr':
                values[col] = ''.join(t.text or '' for t in cell.iter(f'{{{_NS["m"]}}}t'))
            elif kind == 'b' and v is not None:
                values[col] = 'yes' if v.text == '1' else 'no'
            elif v is not None and v.text is not None:
                text = v.text
                # Whole numbers come back as "12.0"-free strings; keep them clean.
                if kind not in ('str', 'e') and re.fullmatch(r'-?\d+\.0+', text):
                    text = text.split('.')[0]
                values[col] = text
        if values:
            width = max(values) + 1
            table.append([values.get(i, '') for i in range(width)])
    return table


def _first_sheet_path(archive):
    workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
    sheet = workbook.find('m:sheets/m:sheet', _NS)
    rel_id = sheet.get(_REL_NS)
    rels = ElementTree.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    for rel in rels:
        if rel.get('Id') == rel_id:
            target = rel.get('Target').lstrip('/')
            return target if target.startswith('xl/') else f'xl/{target}'
    raise KeyError(rel_id)


def _column_index(ref):
    letters = re.match(r'[A-Z]+', ref)
    index = 0
    for ch in letters.group(0) if letters else 'A':
        index = index * 26 + (ord(ch) - 64)
    return index - 1


# ---- cell parsing -------------------------------------------------------

def parse_decimal(text, *, field, required=False, minimum=None):
    text = (text or '').replace(',', '').replace(' ', '').replace('TZS', '').replace('Tsh', '')
    if not text:
        if required:
            raise CellError(f'{field} is required.')
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise CellError(f'{field} "{text}" is not a number.')
    if minimum is not None and value < minimum:
        raise CellError(f'{field} must be at least {minimum}.')
    return value


_TRUE = {'yes', 'y', 'true', '1', 'x', 'ndiyo'}
_FALSE = {'no', 'n', 'false', '0', '', 'hapana'}


def parse_bool(text, *, field):
    value = (text or '').strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise CellError(f'{field} must be yes or no, not "{text}".')


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def parse_date(text, *, field, required=False):
    """Accepts what people actually type for expiry dates: 2027-03-31,
    31/03/2027, 03/2027, 3/27, Mar-2027, or an Excel date number.
    Month-only dates mean the end of that month, as printed on packs."""
    value = (text or '').strip()
    if not value:
        if required:
            raise CellError(f'{field} is required.')
        return None
    if re.fullmatch(r'\d{4,5}(\.\d+)?', value):  # Excel serial day number
        return date(1899, 12, 30) + timedelta(days=int(float(value)))
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%y', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    month_year = re.fullmatch(r'(\d{1,2})[/\-.](\d{2}|\d{4})', value) or None
    if month_year:
        month, year = int(month_year.group(1)), int(month_year.group(2))
    else:
        named = re.fullmatch(r'([A-Za-z]{3})[A-Za-z]*[\s\-/]+(\d{2}|\d{4})', value)
        if not named or named.group(1).lower() not in _MONTHS:
            raise CellError(f'{field} "{value}" is not a date. Use e.g. 2027-03-31 or 03/2027.')
        month, year = _MONTHS[named.group(1).lower()], int(named.group(2))
    if year < 100:
        year += 2000
    if not 1 <= month <= 12:
        raise CellError(f'{field} "{value}" has no month {month}.')
    return date(year, month, calendar.monthrange(year, month)[1])
