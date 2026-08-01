#!/usr/bin/env python3
"""
dify_upload5.py — 2026-07-28 验证通过，5个老师全部成功
用法：scp到服务器，python3执行
"""
import json, uuid, subprocess

TENANT = 'f4194df5-5a62-4558-846c-e20f76586813'
COPY_COLS = ('id, tenant_id, dataset_id, document_id, position, content, '
             'word_count, tokens, keywords, index_node_id, index_node_hash, '
             'hit_count, enabled, disabled_at, disabled_by, status, '
             'created_by, created_at')

teachers = [
    ("老师乙", "c18d25ae-2028-4939-9baf-3e2dd71b7b72", "/tmp/老师乙经验精炼.jsonl"),
    ("老师丙", "975df16c-c5fc-4876-821b-84f585a3c832", "/tmp/老师丙经验精炼.jsonl"),
    ("老师丁",   "8a9e8241-30d9-46ab-8566-0cc52eb68219", "/tmp/老师丁经验精炼.jsonl"),
    ("老师戊", "9dd0682e-d32e-4ed2-bc32-727ecb93c490", "/tmp/老师戊经验精炼.jsonl"),
    ("老师甲", "f8e83086-4186-4511-b965-c48d85021508", "/tmp/老师甲经验精炼_合规.jsonl"),
]

def psql(sql):
    return subprocess.check_output(
        ['docker', 'exec', 'docker-db-1',
         'psql', '-U', 'postgres', '-d', 'dify', '-c', sql],
        stderr=subprocess.STDOUT, timeout=30).decode()

for name, ds_id, jsonl_path in teachers:
    records = [json.loads(l) for l in open(jsonl_path, encoding='utf-8') if l.strip()]
    total_chars = sum(len(r['content']) for r in records)
    doc_id, file_id, batch = str(uuid.uuid4()), str(uuid.uuid4()), f'batch_{file_id}'
    fname = jsonl_path.split('/')[-1]
    print(f"处理 {name}: {len(records)}条, {total_chars}字符")

    psql(f"INSERT INTO upload_files (id, tenant_id, key, name, size, extension, mime_type, created_by, created_by_role, storage_type, used) VALUES ('{file_id}', '{TENANT}', 'upload_files/{ds_id}/{file_id}', '{fname}', {total_chars}, 'jsonl', 'application/jsonl', '{TENANT}', 'account', 'local', false)")
    print("  upload_files: OK")

    psql(f"INSERT INTO documents (id, tenant_id, dataset_id, name, doc_form, doc_language, indexing_status, data_source_type, file_id, word_count, position, created_by, batch, created_from, enabled) VALUES ('{doc_id}', '{TENANT}', '{ds_id}', '{fname}', 'text_model', 'Chinese', 'completed', 'upload_file', '{file_id}', {total_chars}, 1, '{TENANT}', '{batch}', 'api', true)")
    print("  documents: OK")

    seg_lines = []
    for i, rec in enumerate(records):
        seg_id = str(uuid.uuid4())
        content = rec['content'].replace('\t', ' ').replace('\n', ' ').replace("'", "''")
        keywords = json.dumps([rec.get('source', '')], ensure_ascii=False)
        line = f'{seg_id}\t{TENANT}\t{ds_id}\t{doc_id}\t{i+1}\t{content}\t{len(rec["content"])}\t0\t{keywords}\t\\N\t\\N\t0\ttrue\t\\N\t\\N\tdataset\t{TENANT}\tnow()'
        seg_lines.append(line)

    seg_data = ('\n'.join(seg_lines) + '\n').encode('utf-8')
    proc = subprocess.Popen(
        ['docker', 'exec', '-i', 'docker-db-1',
         'psql', '-U', 'postgres', '-d', 'dify', '-c',
         f'COPY document_segments({COPY_COLS}) FROM stdin'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = proc.communicate(seg_data)
    print(f"  COPY: {out.decode()[:50] if out else 'OK'}")

print("\n全部完成")
