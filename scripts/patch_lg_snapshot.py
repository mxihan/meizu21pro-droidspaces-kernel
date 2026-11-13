"""Prepare a reversible LG NEC correction in an owned host-side SQLite copy."""
import argparse
from contextlib import closing
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def filter_from_properties(properties):
    assert len(properties) == 5 and properties[0] < 225
    return {
        'id': lzma.FILTER_LZMA1,
        'dict_size': int.from_bytes(properties[1:], 'little'),
        'lc': properties[0] % 9,
        'lp': properties[0] // 9 % 5,
        'pb': properties[0] // 45,
    }


def decode_epulse(blob):
    assert len(blob) >= 10, 'Incomplete SDK LZMA header'
    size = int.from_bytes(blob[6:10], 'little')
    decoder = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW, filters=[filter_from_properties(blob[1:6])])
    raw = decoder.decompress(blob[10:], max_length=size + 1)
    assert len(raw) == size, 'Decoded length differs from the SDK header'
    return raw.decode('utf-8')


def encode_epulse(text, properties):
    raw = text.encode('utf-8')
    payload = lzma.compress(
        raw, format=lzma.FORMAT_RAW, filters=[filter_from_properties(properties)])
    blob = bytes([(len(raw) >> 1) & 255]) + properties + struct.pack('<I', len(raw)) + payload
    assert decode_epulse(blob) == text
    return blob


def nec_code(frame):
    assert len(frame) == 67 and 8000 <= frame[0] <= 10000 and 3500 <= frame[1] <= 5500
    assert all(250 <= mark <= 950 for mark in frame[2::2])
    spaces = frame[3::2]
    assert all(250 <= value <= 950 or 1200 <= value <= 2100 for value in spaces)
    code = bytearray(4)
    for bit, duration in enumerate(spaces):
        code[bit // 8] |= (duration > 1000) << (bit % 8)
    assert code[0] ^ code[1] == 255 and code[2] ^ code[3] == 255
    return code.hex()


def single_nec_variant(text):
    pulses = [int(value.strip()) for value in text.split(',')]
    assert len(pulses) % 68 in (0, 67), 'Pulse count is outside the supported NEC layout'
    frame_count = (len(pulses) + 1) // 68
    assert frame_count >= 2, 'Already single-frame or unsupported layout'
    codes = [nec_code(pulses[start:start + 67]) for start in range(0, len(pulses), 68)]
    assert len(set(codes)) == 1, 'Frames carry different commands'
    assert all(value > 20000 for value in pulses[67::68]), 'Unexpected NEC inter-frame space'
    corrected = pulses[:67]
    if len(pulses) % 68 == 0:
        corrected.append(pulses[-1])
    return ','.join(map(str, corrected)), {
        'old_pulse_count': len(pulses),
        'new_pulse_count': len(corrected),
        'old_complete_frames': frame_count,
        'nec_bytes': codes[0],
    }


def write_sql(path, patches, reverse=False):
    lines = ['.bail on', 'BEGIN IMMEDIATE;',
             'CREATE TEMP TABLE pixelos_lg_ir_guard (one INTEGER CHECK(one=1));']
    for patch in patches:
        original, corrected = patch['original_hex'], patch['corrected_hex']
        if reverse:
            original, corrected = corrected, original
        lines.append(
            f"UPDATE RemoteKey SET epulse=X'{corrected}' "
            f"WHERE rkid={patch['rkid']} AND did={patch['did']} AND rid={patch['rid']} "
            f"AND epulse=X'{original}';")
        lines.append('INSERT INTO pixelos_lg_ir_guard VALUES(changes());')
    lines.extend(['COMMIT;', 'SELECT count(*) FROM pixelos_lg_ir_guard;'])
    path.write_text('\n'.join(lines) + '\n')


def table_rows(connection, table):
    quoted = '"' + table.replace('"', '""') + '"'
    return sorted(connection.execute(f'SELECT * FROM {quoted}').fetchall(), key=repr)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('snapshot', type=Path)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--did', type=int, default=1)
parser.add_argument('--rid', type=int, default=3668)
selection = parser.add_mutually_exclusive_group()
selection.add_argument('--keys', nargs='+')
selection.add_argument('--all-keys', action='store_true')
parser.add_argument('--apply', action='store_true', help='Write the patched host copy')
args = parser.parse_args()
source = args.snapshot.resolve()
assert source.is_file(), 'Input snapshot does not exist'
destination = args.output_dir.resolve()
destination.mkdir(parents=True, exist_ok=True)
original_db = destination / 'kkappdb.original.sqlite'
patched_db = destination / 'kkappdb.patched.sqlite'
assert source not in (original_db, patched_db), 'Output must use a different path from the input snapshot'
assert not original_db.exists() and not patched_db.exists(), 'Choose a fresh output directory'

source_files = [path for suffix in ('', '-wal', '-shm') if (path := Path(str(source) + suffix)).exists()]
source_digests = {str(path): digest(path) for path in source_files}
with tempfile.TemporaryDirectory(prefix='lg-ir-source-', dir=destination) as directory:
    working = Path(directory) / source.name
    for path in source_files:
        shutil.copy2(path, Path(directory) / path.name)
    with closing(sqlite3.connect(working.as_uri() + '?mode=ro', uri=True)) as reader:
        assert reader.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        with closing(sqlite3.connect(original_db)) as output:
            reader.backup(output)
assert source_digests == {str(path): digest(path) for path in source_files}, 'Input snapshot changed during inspection'

patches, skipped = [], []
keys = None if args.all_keys else (args.keys or ['volume_up', 'volume_down'])
with closing(sqlite3.connect(original_db)) as database:
    database.row_factory = sqlite3.Row
    device = database.execute('SELECT did,rid,dtype,brandName FROM UserDevice WHERE did=?', (args.did,)).fetchone()
    assert device and device['rid'] == args.rid and device['dtype'] == 2 and 'LG' in device['brandName']
    query = 'SELECT rkid,did,rid,fre,fkey,epulse FROM RemoteKey WHERE did=? AND rid=?'
    parameters = [args.did, args.rid]
    if keys:
        query += ' AND fkey IN (' + ','.join('?' for _ in keys) + ')'
        parameters.extend(keys)
    rows = database.execute(query + ' ORDER BY rkid', parameters).fetchall()
    assert rows, 'No requested LG remote keys exist in this snapshot'
    for row in rows:
        try:
            text = decode_epulse(row['epulse'])
            variants = [single_nec_variant(variant) for variant in text.split('&')]
            corrected_text = '&'.join(variant[0] for variant in variants)
            corrected = encode_epulse(corrected_text, row['epulse'][1:6])
        except (AssertionError, ValueError, lzma.LZMAError, UnicodeError, TypeError) as error:
            skipped.append({'rkid': row['rkid'], 'fkey': row['fkey'], 'reason': str(error)})
            continue
        patch = {key: row[key] for key in ('rkid', 'did', 'rid', 'fre', 'fkey')}
        patch.update(original_hex=row['epulse'].hex(), corrected_hex=corrected.hex(),
                     variants=[variant[1] for variant in variants])
        patches.append(patch)

write_sql(destination / 'apply.sql', patches)
write_sql(destination / 'restore.sql', patches, reverse=True)
if args.apply:
    shutil.copyfile(original_db, patched_db)
    with closing(sqlite3.connect(patched_db)) as database:
        database.execute('BEGIN IMMEDIATE')
        for patch in patches:
            result = database.execute('UPDATE RemoteKey SET epulse=? WHERE rkid=? AND epulse=?',
                (bytes.fromhex(patch['corrected_hex']), patch['rkid'], bytes.fromhex(patch['original_hex'])))
            assert result.rowcount == 1
        database.commit()
    with closing(sqlite3.connect(original_db)) as original, closing(sqlite3.connect(patched_db)) as patched:
        assert patched.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert original.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall() == patched.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        replacements = {patch['rkid']: patch for patch in patches}
        tables = [row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            expected, actual = table_rows(original, table), table_rows(patched, table)
            if table == 'RemoteKey':
                columns = [row[1] for row in original.execute('PRAGMA table_info(RemoteKey)')]
                identifier, pulse_column = columns.index('rkid'), columns.index('epulse')
                normalized = []
                for row in actual:
                    fields = list(row)
                    if fields[identifier] in replacements:
                        patch = replacements[fields[identifier]]
                        assert fields[pulse_column] == bytes.fromhex(patch['corrected_hex'])
                        fields[pulse_column] = bytes.fromhex(patch['original_hex'])
                    normalized.append(tuple(fields))
                actual = sorted(normalized, key=repr)
            assert expected == actual, f'Unexpected data change in {table}'

report = {
    'source_files_sha256': source_digests,
    'source_quiescence': 'Caller must export DB and existing WAL after stopping the app',
    'did': args.did, 'rid': args.rid,
    'mode': 'patched-host-copy' if args.apply else 'dry-run',
    'patches': patches, 'skipped': skipped,
    'phone_modified': False,
    'native_decoder_executed': False,
    'patched_copy': str(patched_db) if args.apply else None,
    'other_columns_and_tables_verified_equal': bool(args.apply),
}
(destination / 'manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
for patch in patches:
    print(json.dumps({key: value for key, value in patch.items() if not key.endswith('_hex')}, ensure_ascii=False))
for row in skipped:
    print(json.dumps({'skipped': row}, ensure_ascii=False))
print(json.dumps({'mode': report['mode'], 'changed_rows': len(patches), 'phone_modified': False,
                  'other_columns_and_tables_verified_equal': bool(args.apply)}))
