from pathlib import Path
import subprocess, json, re, zipfile
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfReader
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent.parent
POPPLER=Path(r'C:\Users\ruoxiao\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe')
pdfs=list(ROOT.glob('*.pdf'))+list((ROOT/'_qa').glob('*.pdf'))

def render(path):
    folder=ROOT/'_qa'/path.stem[:2]
    folder.mkdir(exist_ok=True)
    subprocess.run([str(POPPLER),'-scale-to','1400','-png',str(path),str(folder/'page')],check=True,capture_output=True)
    pdf=PdfReader(path)
    pages=[]
    for i,p in enumerate(pdf.pages,1):
        t=p.extract_text() or ''
        pages.append({'page':i,'characters':len(t),'links':len(p.get('/Annots',[])), 'start':t[:80], 'end':t[-100:]})
    return {'file':path.name,'pages':pages}

with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(render,pdfs))
(ROOT/'_qa'/'page_report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
for x in results: print(x['file'],len(x['pages']))

for code in ['01','02','05','06']:
    paths=sorted((ROOT/'_qa'/code).glob('page-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
    for start in range(0,len(paths),6):
        group=paths[start:start+6]
        sheet=Image.new('RGB',(930,700*((len(group)+2)//3)),'#ddd')
        d=ImageDraw.Draw(sheet)
        for i,path in enumerate(group):
            img=Image.open(path); img.thumbnail((300,665))
            x=(i%3)*310; y=(i//3)*700
            sheet.paste(img,(x,y+25)); d.text((x+5,y+5),f'{code} / {path.stem}',fill='black')
        sheet.save(ROOT/'_qa'/f'contact_{code}_{start//6+1}.jpg')

# Check only the newly authored output files, never inspect private environment files.
for code,count in [('05',48),('06',40)]:
    path=next(ROOT.glob(code+'*.md'))
    t=path.read_text(encoding='utf-8')
    ids=[int(x) for x in re.findall(r'^### (\d+) ',t,re.M)]
    assert ids==list(range(1,count+1)),(path.name,ids)
    assert not re.search(r'(?:sk-|pat_|cztei_)[A-Za-z0-9]{12,}',t)
for code in ['01','02']:
    path=next(ROOT.glob(code+'*.pdf'))
    reader=PdfReader(path)
    assert len(reader.pages)==1
    t=reader.pages[0].extract_text()
    assert '黄健鸿' in t and '13189576720' in t and '2028' in t
    assert len(reader.pages[0].get('/Annots',[]))>=2
print('Page count, contacts, hyperlinks, question numbering, and credential-pattern checks passed.')
