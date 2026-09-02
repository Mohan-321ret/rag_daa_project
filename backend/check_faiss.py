import os
import pickle
import faiss

index_file = 'data/faiss_index.index'
meta_file = 'data/faiss_index.pkl'

print("--- FAISS Vector Database Status ---")

if not os.path.exists(index_file) or not os.path.exists(meta_file):
    print("No FAISS index found. It will be created when you upload the first document.")
    exit(0)

# Load the FAISS index
index = faiss.read_index(index_file)
print(f"Index loaded successfully.")
print(f"Total Vectors stored : {index.ntotal}")
print(f"Vector dimensions    : {index.d}")

# Load the metadata map
with open(meta_file, 'rb') as f:
    meta_data = pickle.load(f)

id_map = meta_data.get('id_map', {})
print(f"Metadata entries     : {len(id_map)}")

print("\n--- First 3 Stored Vectors (Metadata) ---")
count = 0
for faiss_id, data in id_map.items():
    if count >= 3:
        break
    doc_id = data.get('metadata', {}).get('document_id', 'Unknown')
    chunk_idx = data.get('metadata', {}).get('chunk_index', 'Unknown')
    text = data.get('text', '')[:60].replace('\n', ' ')
    print(f"FAISS ID {faiss_id:2d} | Doc: {doc_id} (Chunk {chunk_idx}) | Text: '{text}...'")
    count += 1
