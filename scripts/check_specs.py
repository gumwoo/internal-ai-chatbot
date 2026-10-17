"""Read-only specification/link/PDF checks; does not test a future backend."""
from pathlib import Path
import hashlib, json, re, os
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
errors=[]
files=list((ROOT/'docs').rglob('*.md'))+[ROOT/'README.md']
links=0
for p in files:
    s=p.read_text(encoding='utf-8')
    if s.count('```')%2: errors.append(f'{p.relative_to(ROOT)}: unclosed fence')
    for block in re.findall(r'```json\s*\n(.*?)```',s,re.S):
        try: json.loads(block)
        except json.JSONDecodeError as e: errors.append(f'{p.name}: JSON {e}')
    for target in re.findall(r'\[[^\]\n]*\]\(([^)\n]+)\)',s):
        if target.startswith(('http:','https:','app:','codex:','#','mailto:')): continue
        target=unquote(target.split('#')[0].strip('<>'))
        if not target: continue
        links+=1
        if not (p.parent/target).exists(): errors.append(f'{p.relative_to(ROOT)}: missing {target}')
shared=(ROOT/'docs/contracts/00-shared-contracts.md').read_text(encoding='utf-8')
tests=(ROOT/'docs/07-test-and-evaluation.md').read_text(encoding='utf-8')
assert len(re.findall(r'^## CT-\d{2} ',shared,re.M))==16
assert len(re.findall(r'^\| T-\d{2} \|',tests,re.M))==35
assert len(list((ROOT/'docs/modules').glob('MOD-*.md')))==12
# Check the four corrected contracts are represented at the public boundaries.
required={
 'docs/14-ticket-workflow.md':['draft','superseded','CP-07','expected_head_id','PREPARE_PAYLOAD_CONFLICT'],
 'docs/contracts/00-shared-contracts.md':['CP-07','processing_date','knowledge_as_of','unsupported','TicketPage'],
 'docs/corpus/01-metadata-contract.md':['document_role','available_from','application_basis'],
 'docs/03-data-model.md':['ticket_prepare_receipts','application_basis','PDF SHA-256'],
 'docs/04-api-spec.md':['ACTION_NOT_PREPARED','ACTION_SUPERSEDED','동일 키/본문 POST replay'],
}
for name,words in required.items():
    body=(ROOT/name).read_text(encoding='utf-8')
    for word in words:
        if word not in body: errors.append(f'{name}: missing contract term {word}')
# PDF integrity inventory is an output report only. Existing originals are never rewritten.
pdfs=sorted((ROOT/'data/raw/pdfs').glob('*.pdf'))
assert len(pdfs)==100
hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pdfs}
report_dir=Path(os.environ.get('SPEC_RESULTS_DIR',str(ROOT/'.impeccable/review'))).resolve();report_dir.mkdir(parents=True,exist_ok=True)
baseline=ROOT/'.impeccable/review/state-contract-pdf-hashes.json'
if baseline.exists():
    if json.loads(baseline.read_text(encoding='utf-8'))!=hashes: errors.append('PDF hash inventory changed since this verification baseline')
else: baseline.write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
report={'scope':'Static specification checks, not semantic proof or server tests','markdown_files':len(files),'local_links':links,'pdf_files':len(pdfs),'ct':16,'modules':12,'test_ids':35,'errors':errors}
(report_dir/'third-review-spec-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(bool(errors))
