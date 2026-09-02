import urllib.request, json, time

BASE_URL = 'http://localhost:8000'

def post_file(path, filename, filepath):
    boundary = '----BoundaryXYZ'
    with open(filepath, 'rb') as f:
        content = f.read()
    
    file_part = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n'
        f'Content-Type: text/plain\r\n\r\n'
    ).encode() + content
    
    body = file_part + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read())

def get(path):
    resp = urllib.request.urlopen(BASE_URL + path)
    return json.loads(resp.read())

def post_json(path, data):
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

print('Uploading test_upload.txt...')
upload_res = post_file('/api/v1/documents/upload', 'test_upload.txt', 'test_upload.txt')
print(json.dumps(upload_res, indent=2))

# Upload is now an async job (Admin Panel: Data Injection Management) —
# the POST above only returns job_id/status='queued'; poll for the result.
job_id = upload_res['job_id']
job = {}
for _ in range(120):
    job = get(f'/api/v1/ingestion-jobs/{job_id}')
    if job['status'] in ('completed', 'failed', 'cancelled'):
        break
    time.sleep(0.5)
print(json.dumps(job, indent=2))

doc_id = job.get('document_id')
doc_res = get(f'/api/v1/documents/{doc_id}') if doc_id else {}
if doc_res.get('processing_status') == 'indexed':
    print(f'\nFetching chunks for {doc_id}...')
    chunks_res = get(f'/api/v1/chunks/{doc_id}')
    print(f'Found {chunks_res["total"]} chunks.')
    for c in chunks_res['chunks'][:3]:
        print(f' - Chunk {c["chunk_index"]}: {c["word_count"]} words | {c["text"][:80]}...')

    print('\nTesting Semantic Search for "CNN Evaluation"...')
    search_res = post_json('/api/v1/chunks/search', {'query': 'CNN Evaluation metrics accuracy precision recall', 'top_k': 3})
    for r in search_res['results']:
        print(f' - Score: {r["score"]:.4f} | Text: {r["text"][:80]}...')
else:
    print('Document not indexed properly.')
