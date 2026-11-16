#!/usr/bin/env python3
"""Write the scan time corpus of docs/DIFFERENCES.md into <outdir> (standard library only, seeded).

  make-corpus.py <outdir>

doc9.docx, plain9.zip, nested9.zip and pdf9.pdf are about 9 MB each; pay/ holds the files make-rar.sh packs into RAR
archives of the same size. Nothing here writes RAR.
"""

import os, random, sys, zipfile, zlib, struct, io
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
rnd = random.Random(1544)
def rb(n): return rnd.randbytes(n)
words = [rnd.randbytes(rnd.randint(3,9)).hex()[:rnd.randint(3,9)] for _ in range(4000)]
def text(n):
    parts=[];t=0
    while t<n:
        s=' '.join(rnd.choice(words) for _ in range(rnd.randint(8,20)))+'.\n'
        parts.append(s);t+=len(s)
    return ''.join(parts).encode()[:n]
def png(w,h):
    raw=b''.join(b'\0'+rb(w*3) for _ in range(h))
    def ch(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+ch(b'IDAT',zlib.compress(raw,1))+ch(b'IEND',b'')
def docx(path, nimg, imgsz, textsz):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        body=''.join('<w:p><w:r><w:t>%s</w:t></w:r></w:p>'%l for l in text(textsz).decode().split('\n'))
        z.writestr('word/document.xml','<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>%s</w:body></w:document>'%body)
        for i in range(nimg):
            side=int((imgsz/3)**0.5)
            z.writestr('word/media/image%d.png'%i,png(side,side))
docx(out+'/doc9.docx',3,3_000_000,600_000)
def payload(d, nfiles, rand_total, text_total):
    os.makedirs(d,exist_ok=True)
    for i in range(nfiles):
        open('%s/f%02d.bin'%(d,i),'wb').write(rb(rand_total//nfiles))
        open('%s/f%02d.txt'%(d,i),'wb').write(text(text_total//nfiles))
payload(out+'/pay',30,4_200_000,12_000_000)
with zipfile.ZipFile(out+'/plain9.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(out+'/pay')): z.write(out+'/pay/'+f,f)
# nested: zip of zips, three levels, ~9 MB
def zipbytes(files):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for n,d in files: z.writestr(n,d)
    return b.getvalue()
inner=[zipbytes([('a%d.bin'%i,rb(750_000)),('a%d.txt'%i,text(1_500_000))]) for i in range(6)]
mid=[zipbytes([('in%d_%d.zip'%(j,k),inner[j*2+k]) for k in range(2)] ) for j in range(3)]
open(out+'/nested9.zip','wb').write(zipbytes([('mid%d.zip'%i,m) for i,m in enumerate(mid)]))
# pdf: image streams
def pdf(path,nimg,side):
    objs=[];
    objs.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    kids=' '.join('%d 0 R'%(3+i*3) for i in range(nimg))
    objs.append(('<< /Type /Pages /Kids [%s] /Count %d >>'%(kids,nimg)).encode())
    for i in range(nimg):
        pg=3+i*3
        raw=zlib.compress(rb(side*side*3),1)
        objs.append(('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /XObject << /Im0 %d 0 R >> >> >>'%(pg+1,pg+2)).encode())
        c=b'q 612 0 0 792 0 0 cm /Im0 Do Q'
        objs.append(('<< /Length %d >>\nstream\n'%len(c)).encode()+c+b'\nendstream')
        objs.append(('<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n'%(side,side,len(raw))).encode()+raw+b'\nendstream')
    out=bytearray(b'%PDF-1.5\n'); offs=[]
    for i,o in enumerate(objs):
        offs.append(len(out)); out+=('%d 0 obj\n'%(i+1)).encode()+o+b'\nendobj\n'
    x=len(out); out+=('xref\n0 %d\n0000000000 65535 f \n'%(len(objs)+1)).encode()
    for o in offs: out+=('%010d 00000 n \n'%o).encode()
    out+=('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'%(len(objs)+1,x)).encode()
    open(path,'wb').write(out)
pdf(out+'/pdf9.pdf',3,1000)
