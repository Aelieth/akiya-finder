#!/usr/bin/env python3
"""Akiya scraper: Ena / Hashimoto / Tatsuno official akiya banks -> site/listings.json"""
import re, json, os, time, hashlib, subprocess, datetime, urllib.parse, glob
import requests
from bs4 import BeautifulSoup as B
D=os.path.dirname(os.path.abspath(__file__)); SITE=os.environ.get("AKIYA_SITE",f"{D}/site"); CACHE=os.environ.get("AKIYA_CACHE",f"{D}/cache")
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 (akiya-finder; personal daily check, 1 req/s)'
TSUBO=3.3058; TODAY=datetime.date.today().isoformat()
errors=[]
def get(u,binary=False):
    time.sleep(0.7); r=S.get(u,timeout=40); r.raise_for_status()
    if binary: return r.content
    r.encoding=r.apparent_encoding if 'charset' not in r.headers.get('content-type','') else r.encoding
    return r.text
USED=set()
def pdffile(u,lid,tag='info'):
    os.makedirs(f"{SITE}/pdf",exist_ok=True)
    name=f"{lid}-{tag}.pdf"; p=f"{SITE}/pdf/{name}"; USED.add(name)
    if not os.path.exists(p): open(p,'wb').write(get(u,True))
    return p, f"pdf/{name}"
def pdftext(u,lid):
    p,_=pdffile(u,lid)
    t=subprocess.run(['pdftotext','-layout',p,'-'],capture_output=True,text=True).stdout
    if len(t.strip())<50 and subprocess.run(['which','tesseract'],capture_output=True).returncode==0:
        subprocess.run(['pdftoppm','-png','-r','200',p,f"{CACHE}/ocr"],check=False)
        t=''.join(subprocess.run(['tesseract',f,'-','-l','jpn'],capture_output=True,text=True).stdout for f in sorted(glob.glob(f"{CACHE}/ocr*.png")))
        for f in glob.glob(f"{CACHE}/ocr*.png"): os.remove(f)
    return t
def pdfphoto(u,lid):
    out=f"{SITE}/img/{lid}.jpg"; USED.add(f"img:{lid}.jpg")
    if os.path.exists(out): return f"img/{lid}.jpg"
    try:
        p=f"{CACHE}/{lid}-photo.pdf"
        if not os.path.exists(p): open(p,'wb').write(get(u,True))
        subprocess.run(['pdftoppm','-jpeg','-r','50','-f','1','-l','1','-singlefile',p,out[:-4]],check=True)
        return f"img/{lid}.jpg"
    except Exception as e: errors.append(f"photo {lid}: {e}"); return None
def num(s):
    try: return float(s.replace(',',''))
    except: return None
def yen(t):
    t=t.replace(',','')
    m=re.search(r'([\d.]+)\s*万円',t)
    if m: return int(float(m.group(1))*10000)
    m=re.search(r'(\d+)\s*円',t); return int(m.group(1)) if m else None

def ena():
    out=[]; ids=[]; page=1
    while True:
        u="https://kurashi.enalifebizsupport.jp/akiyabank/"+(f"page/{page}/" if page>1 else "")
        try: h=get(u)
        except Exception: break
        new=[x for x in dict.fromkeys(re.findall(r'akiyabank/(\d+)/"',h)) if x not in ids]
        if not new: break
        ids+=new; page+=1
        if page>20: break
    for i in ids:
        u=f"https://kurashi.enalifebizsupport.jp/akiyabank/{i}/"
        try:
            s=B(get(u),'html.parser'); m=s.find('main') or s.body; t=m.get_text('\n',strip=True)
            g=lambda k: (re.search(k+r'\n(.+)',t) or [None,''])[1]
            area=g('所在地'); price=g('希望価格'); kind=g(r'物件番号：\d+\n(?:NEW\n)?[^\n]+') 
            L=dict(id=f"ena-{i}",city="Ena",source_url=u,title=f"恵那市 No.{i} {area}",address=f"岐阜県恵那市{area}",
                   price_text=price,price_yen=yen(price),rent='賃貸' in price,status=(re.search(r'物件番号：\d+\n(?:NEW\n)?(.+)',t) or [None,''])[1],
                   notes=(re.search(r'特記事項\n(.*?)詳細情報',t,re.S) or [None,''])[1].strip()[:800])
            L['farmland']='農地' in t[:600] or '農地付き' in t
            pdf=next((a['href'] for a in m.find_all('a',href=True) if a['href'].endswith('.pdf') and 'riyoutouroku' not in a['href']),None)
            img=next((a['src'] for a in m.find_all('img',src=True) if '/uploads/' in a['src'] and a['src'].endswith('.jpg')),None)
            L['photo']=img
            if pdf:
                pt=pdftext(pdf,L['id']); L['pdf_src']=pdf; L['pdf']=f"pdf/{L['id']}-info.pdf"; L['format']='HTML detail page + PDF card + JPG photos'
                am=re.search(r'物件所在地\s+([^\n]+)',pt)
                if am:
                    a=re.sub(r'\s+','',am.group(1)).replace('恵那市','')
                    a=re.split(r'[0-9,]+万円|希望価格',a)[0]
                    if len(a)>len(area) and a.startswith(area[:2]): L['address']=f"岐阜県恵那市{a}"
                st=re.search(r'([^\s（(]+駅)',pt); L['landmark']=st.group(1) if st else None
                seg=pt[pt.find('面積'):]
                mm=re.search(r'([\d,]+\.?\d*)\s*㎡',seg); L['land_m2']=num(mm.group(1)) if mm else None
                mm=re.search(r'合計\s+([\d,.]+)\s*㎡',pt)
                if mm: L['building_m2']=num(mm.group(1))
                else:
                    fl=re.findall(r'[B１２12]?\s*[１２12]?階\s+([\d,]+\.\d+)\s*㎡',seg[:1500]); L['building_m2']=round(sum(num(x) for x in fl),2) if fl else None
                fm=re.search(r'付属農地等[^\n]*',pt)
                if fm and re.search(r'[田畑山林]',fm.group(0)) and re.search(r'\d',fm.group(0)):
                    L['farmland']=True; L['farmland_note']=re.sub(r'\s+',' ',fm.group(0))[:200]
                    L['extra_land_m2']=sum(num(x) or 0 for x in re.findall(r'([\d,]+\.?\d*)\s*㎡',fm.group(0))) or None
                mm=re.search(r'付属農地等[^\n]*\n?[^\n]*(田|畑|山林)[^\n]*',pt)
                if re.search(r'農地.*?(\d[\d,.]*)\s*㎡',pt): L['farmland_note']=re.search(r'[^\n]*農地[^\n]*',pt).group(0).strip()[:200]
            out.append(L)
        except Exception as e: errors.append(f"ena {i}: {e}")
    return out

def hashimoto():
    out=[]; base="https://www.city.hashimoto.lg.jp/guide/kensetsubu/kentikujutaku/jutakusisaku/akiya/akiyabank_bukkenjyouhou/"
    for page,kind in [("02baibai.html","sale"),("01chintai.html","rent"),("03free.html","free")]:
        try: s=B(get(base+page),'html.parser')
        except Exception as e: errors.append(f"hashimoto {page}: {e}"); continue
        for h in s.find_all('h2'):
            m=re.search(r'【\s*([0-9０-９]+)\s*】',h.text)
            if not m: continue
            no=m.group(1).translate(str.maketrans('０１２３４５６７８９','0123456789')).zfill(3)
            if '成約' in h.text: continue
            blk=[]; pdfs=[]; ig=None
            for el in h.find_all_next():
                if el.name=='h2': break
                if el.name in('a','blockquote') and 'instagram.com/p/' in (el.get('href') or el.get('data-instgrm-permalink') or '') and not ig: ig=(el.get('href') or el.get('data-instgrm-permalink')).split('?')[0]
                if el.name=='a' and '.pdf' in el.get('href',''): pdfs.append(('https:'+el['href'] if el['href'].startswith('//') else el['href'],el.text))
                if el.name in('p','h3','li'): blk.append(el.get_text(' ',strip=True))
            bt='\n'.join(blk); area=(re.search(r'エリア\n(.+)',bt) or [None,''])[1]
            if not area and blk: area=blk[0]
            price=next((x for x in blk if '円' in x),'')
            L=dict(id=f"hashimoto-{no}",city="Hashimoto",source_url=base+page+f"#{no}",title=f"橋本市 No.{no} {area}",
                   address=f"和歌山県橋本市{area}",price_text=' / '.join(x for x in blk if '円' in x)[:120],price_yen=yen(price),
                   instagram=ig,rent=kind=='rent',status=('先着交渉者有' if '先着' in h.text else ''),farmland=False)
            info=next((u for u,t in pdfs if '物件情報' in t),None); photo=next((u for u,t in pdfs if '写真' in t),None)
            if info:
                try:
                    pt=pdftext(info,L['id']); L['pdf_src']=info; L['pdf']=f"pdf/{L['id']}-info.pdf"; L['format']='HTML index + PDF info/floorplan/photo sheets + Instagram'
                    mm=re.search(r'敷地情報.*?面積\s*([\d,.]+)\s*㎡',pt,re.S) or re.search(r'面積\s*([\d,.]+)\s*㎡',pt); L['land_m2']=num(mm.group(1)) if mm else None
                    mm=re.search(r'延床\s*([\d,.]+)\s*㎡',pt); L['building_m2']=num(mm.group(1)) if mm else None
                    mm=re.search(r'付属\s*種類(.*?)条件等',pt,re.S) or re.search(r'付属.*?\n.*?土地[^\n]*',pt)
                    fl=re.search(r'土地\s*合計\s*(.+?)\s{2,}.*?([\d,.]+)\s*㎡',pt)
                    seg=pt[pt.find('付属'):pt.find('ＰＲ')] if '付属' in pt else ''
                    if re.search(r'田|畑|山林',seg):
                        L['farmland']=True; L['farmland_note']=re.sub(r'\s+',' ',seg)[:200]
                        a=re.findall(r'([\d,.]+)\s*㎡',seg); L['extra_land_m2']=sum(num(x) or 0 for x in a) or None
                    st=re.search(r'駅[^\n]*?線\s+(\S+)\s+駅',pt); L['landmark']=(st.group(1)+'駅') if st else None
                    L['notes']=re.sub(r'[ \t]+',' ',pt[pt.find('ＰＲ'):])[:800] if 'ＰＲ' in pt else ''
                except Exception as e: errors.append(f"hashimoto pdf {no}: {e}")
            if photo: L['photo']=pdfphoto(photo,L['id'])
            out.append(L)
    return out

def tatsuno():
    out=[]
    for pid,area in [(1410,'龍野'),(1514,'新宮'),(1522,'揖保川'),(1527,'御津')]:
        u=f"https://www.city.tatsuno.lg.jp/iju/akiya-bank/{pid}.html"
        try: s=B(get(u),'html.parser')
        except Exception as e: errors.append(f"tatsuno {pid}: {e}"); continue
        for h in s.find_all('h2'):
            m=re.search(r'物件(?:番号|登録)\s*(\d+)',h.text)
            if not m: continue
            no=m.group(1); d={}; img=None
            for el in h.find_all_next():
                if el.name=='h2': break
                if el.name=='img' and not img: img='https:'+el['src'] if el['src'].startswith('//') else el['src']
                if el.name=='tr' and el.th and el.td: d[el.th.get_text(strip=True)]=el.td.get_text(' ',strip=True)
            if not d: continue
            f=lambda k: num((re.search(r'([\d,.]+)',d.get(k,'')) or [None,''])[1])
            att=d.get('付帯物件','')
            L=dict(id=f"tatsuno-{no}",city="Tatsuno",source_url=u+f"#{no}",title=f"たつの市 No.{no} {d.get('所在地','')}",
                   address=f"兵庫県たつの市{d.get('所在地','')}",price_text=d.get('売買価格','')+(' / 賃貸 '+d['賃貸価格'] if d.get('賃貸価格','') not in('','―','なし') else ''),
                   price_yen=yen(d.get('売買価格','')),rent=d.get('分類','')!='売却',status=d.get('分類',''),
                   pdf=None,building_m2=f('延床面積'),land_m2=f('土地面積'),photo=img,area=area,format='HTML table + photo image + PDF card/floorplan/photos',
                   notes=' | '.join(f"{k}: {d[k]}" for k in ('間取り','構造','建築年','都市計画','交通','現状等') if k in d))
            st=re.search(r'([^\s　]+駅)',d.get('交通','')); L['landmark']=st.group(1) if st else None
            card=next((a['href'] for a in h.find_all_next('a',href=True,limit=6) if 'card' in a['href'].lower() or '登録カード' in a.text),None)
            if card:
                card='https:'+card if card.startswith('//') else card
                try: pdffile(card,L['id']); L['pdf']=f"pdf/{L['id']}-info.pdf"; L['pdf_src']=card
                except Exception as e: errors.append(f"tatsuno pdf {no}: {e}")
            if att and att not in('なし','―'):
                L['farmland']=bool(re.search(r'田|畑|山林',att)); L['farmland_note']=att
                L['extra_land_m2']=sum(num(x) or 0 for x in re.findall(r'([\d,]+(?:\.\d+)?)\s*平方メートル',att)) or None
            else: L['farmland']=False
            out.append(L)
    return out

SUUMO={'Ena':'gifu/sc_ena','Hashimoto':'wakayama/sc_hashimoto','Tatsuno':'hyogo/sc_tatsuno'}
PREF={'Ena':'岐阜県恵那市','Hashimoto':'和歌山県橋本市','Tatsuno':'兵庫県たつの市'}
def suumo():
    # Facts only (price/sizes/address/station) + link out; no photos or descriptions copied (SUUMO terms: private use).
    out=[]
    for city,path in SUUMO.items():
        page=1
        while page<=10:
            u=f"https://suumo.jp/chukoikkodate/{path}/"+(f"?page={page}" if page>1 else "")
            s=B(get(u),'html.parser'); units=s.select('div.property_unit')
            for it in units:
                d={}
                for dl in it.select('dl'):
                    dt=dl.find('dt'); dd=dl.find('dd')
                    if dt and dd: d[dt.get_text(strip=True)]=dd.get_text(' ',strip=True)
                a=it.select_one('a[href*="/nc_"]')
                if not a: continue
                nc=re.search(r'nc_(\d+)',a['href']).group(1)
                m2=lambda k: num((re.search(r'([\d,.]+)\s*m',d.get(k,'')) or [None,''])[1])
                p=d.get('販売価格',''); pm=re.search(r'(?:(\d+)億)?\s*(\d+)?万円',p.replace(',',''))
                price=(int(pm.group(1) or 0)*100000000+int(pm.group(2) or 0)*10000) if pm else None
                adr=d.get('所在地','').replace(' ','')
                if not adr.startswith(PREF[city][:3]): adr=PREF[city]+adr.replace(PREF[city][3:],'',1)
                st=re.search(r'「(.+?)」',d.get('沿線・駅',''))
                lt='akiya' if re.search(r'空き?家|古民家',it.get_text(' ')) else 'used'
                out.append(dict(id=f"suumo-{nc}",city=city,source='private',source_name='SUUMO',source_url="https://suumo.jp"+a['href'].split('?')[0],
                    title=f"SUUMO {d.get('物件名','') or adr.replace(PREF[city],'')}",address=adr,price_text=p,price_yen=price,rent=False,status='',
                    building_m2=m2('建物面積'),land_m2=m2('土地面積'),photo=None,farmland=False,listing_type=lt,
                    landmark=(st.group(1)+'駅') if st else None,notes=' | '.join(f"{k}: {d[k]}" for k in ('間取り','築年月','沿線・駅') if k in d)))
            if not s.select_one(f'a[href*="page={page+1}"]'): break
            page+=1
    return out
def dedupe(city_bank,private):
    keep=[]
    for p in private:
        dup=None
        for c in city_bank:
            if c['city']!=p['city']: continue
            town=re.sub(r'^'+PREF[c['city']],'',c['address'])[:4]
            if not town or town not in p['address']: continue
            sb=lambda a,b: a and b and abs(a-b)/max(a,b)<0.06
            if (sb(c.get('building_m2'),p.get('building_m2')) and sb(c.get('land_m2'),p.get('land_m2'))) or (sb(c.get('building_m2'),p.get('building_m2')) and c.get('price_yen')==p.get('price_yen')):
                dup=c; break
        if dup:
            dup.setdefault('also_on',[]).append({'name':p['source_name'],'url':p['source_url'],'address':p['address']})
            if len(p['address'])>len(dup['address']): dup['address_private']=p['address']
        else: keep.append(p)
    return keep
AREAS=json.load(open(f"{D}/areas.json")) if os.path.exists(f"{D}/areas.json") else {}
GEO=f"{D}/geocache.json"; geo=json.load(open(GEO)) if os.path.exists(GEO) else {}
CENTER={'Ena':(35.4494,137.4127),'Hashimoto':(34.3149,135.6056),'Tatsuno':(34.8580,134.5455)}
def geocode(L):
    a=L['address']; q=a
    while q not in geo:
        try:
            time.sleep(0.4); r=S.get("https://msearch.gsi.go.jp/address-search/AddressSearch",params={'q':q},timeout=20).json()
            r=[x for x in r if x['properties']['title'].startswith(q[:6])]
            geo[q]=r[0]['geometry']['coordinates'][::-1] if r else None
        except Exception: geo[q]=None
        if geo[q] is None and len(q)>6: q=q[:-1]; continue
        break
    c=geo.get(q)
    if c: L['lat'],L['lng']=c; L['geo_approx']=True; L['geo_level']='town' if q==a else 'partial'
    else: L['lat'],L['lng']=CENTER[L['city']]; L['geo_approx']=True; L['geo_level']='city-center'
    # jitter so same-town listings don't stack
    h=int(hashlib.md5(L['id'].encode()).hexdigest()[:6],16); L['lat']+=((h%100)-50)*0.00006; L['lng']+=((h//100%100)-50)*0.00006

def addr(L):
    a=L.get('address') or ''; town=re.sub(r'^(岐阜県恵那市|和歌山県橋本市|兵庫県たつの市)','',a)
    if re.search(r'[0-9０-９]+(番|$|-)',town): L['address_level']='full'
    elif town: L['address_level']='town'
    else: L['address_level']='none'
    L['maps_query']=a if town else {'Ena':'岐阜県恵那市','Hashimoto':'和歌山県橋本市','Tatsuno':'兵庫県たつの市'}[L['city']]
    if L['address_level']!='full':
        L['approx_note']=f"No street address listed — approx: {town or 'city only'}"+(f" (near {L['landmark']})" if L.get('landmark') else '')
def fx(prev):
    for u,k in [("https://open.er-api.com/v6/latest/JPY",lambda j:j['rates']['USD']),("https://api.frankfurter.app/latest?from=JPY&to=USD",lambda j:j['rates']['USD'])]:
        try: return {'jpy_usd':k(S.get(u,timeout=20).json()),'date':TODAY,'source':u.split('/')[2]}
        except Exception as e: errors.append(f"fx {u}: {e}")
    return prev
def classify(L):
    addr(L)
    b=L.get('building_m2'); l=L.get('land_m2') or 0; tot=l+(L.get('extra_land_m2') or 0)
    L['land_tsubo']=round(l/TSUBO,1) if l else None; L['total_land_m2']=round(tot,2) if tot else None
    L['total_land_tsubo']=round(tot/TSUBO,1) if tot else None
    bok=b is not None and 150<=b<=200; lok=tot>=1983
    L['match']=bool(bok and lok and not L.get('rent'))
    near_b=b is not None and 120<=b<=240; near_l=tot>=1300
    L['near_match']=not L['match'] and ((bok and near_l) or (near_b and lok) or (near_b and L.get('farmland')))
    L['has_extra_land']=bool(L.get('farmland') or L.get('extra_land_m2'))

if __name__=='__main__':
    srcs={'Ena (kurashi.enalifebizsupport.jp, official city bank site)':('ena',ena),'Hashimoto (city.hashimoto.lg.jp)':('hashimoto',hashimoto),'Tatsuno (city.tatsuno.lg.jp)':('tatsuno',tatsuno),'SUUMO 中古一戸建て (private)':('suumo',suumo)}
    try: prev=json.load(open(f"{SITE}/listings.json")).get('listings',[])
    except Exception: prev=[]
    cur=[]; status={}; okpfx=set(); private=[]
    for k,(pfx,fn) in srcs.items():
        try:
            r=fn()
            if not r: raise RuntimeError('0 listings (layout change?)')
            status[k]=len(r); okpfx.add(pfx)
        except Exception as e:
            r=[x for x in prev if x['id'].startswith(pfx+'-')]  # fail-safe: keep yesterday's
            status[k]=f"FAILED (kept {len(r)} from previous run): {e}"; errors.append(f"{k}: {e}")
        for x in r: x.setdefault('source','city' if pfx!='suumo' else 'private'); x.setdefault('listing_type','akiya'); x.setdefault('source_name',{'ena':'Ena city bank','hashimoto':'Hashimoto city bank','tatsuno':'Tatsuno city bank'}.get(pfx,'SUUMO')); x.pop('also_on',None)
        (private if pfx=='suumo' else cur).extend(r)
    np=len(private); private=dedupe(cur,private); status['dedupe']=f"{np-len(private)} private listings merged into city-bank entries"
    cur+=private
    HIST=f"{D}/history.json"; hist=json.load(open(HIST)) if os.path.exists(HIST) else {}
    firstrun=not hist; ids=set(); base=hist.pop('_baseline',{}).get('date',TODAY)
    sb=hist.pop('_src_baseline',{})
    for L in cur:
        if L.get('address_private') and L['address_private'] not in L['address']: L['address']=L['address_private']
        geocode(L); classify(L); ids.add(L['id'])
        pa=[a for a in AREAS.get(L['city'],[]) if a in L['address']]; L['preferred']=bool(pa); L['preferred_area']=pa[0] if pa else None
        h=hist.get(L['id'],{}); L['first_seen']=h.get('first_seen',TODAY); L['last_seen']=TODAY
        pf=L['id'].split('-')[0]; sb.setdefault(pf,TODAY)
        L['new']=(L['first_seen']>max(base,sb[pf])) and (datetime.date.fromisoformat(L['first_seen'])>=datetime.date.today()-datetime.timedelta(days=7))
        hist[L['id']]={'first_seen':L['first_seen'],'last_seen':TODAY,'title':L['title'],'removed':None}
    hist['_baseline']={'date':base}; hist['_src_baseline']=sb
    for k,h in hist.items():
        if k.startswith('_'): continue
        if k not in ids and not h.get('removed') and k.split('-')[0] in okpfx: h['removed']=TODAY
    # purge assets of listings no longer on source (only for cities that scraped OK)
    purged=0
    if not any('FAILED' in str(v) for v in status.values()):
        for f in glob.glob(f"{SITE}/pdf/*.pdf"):
            if os.path.basename(f) not in USED: os.remove(f); purged+=1
        for f in glob.glob(f"{SITE}/img/*.jpg"):
            if 'img:'+os.path.basename(f) not in USED: os.remove(f); purged+=1
        for f in glob.glob(f"{CACHE}/*.pdf"):
            if os.path.basename(f).split('-photo')[0] not in ids: os.remove(f); purged+=1
    print('purged assets',purged)
    json.dump(geo,open(GEO,'w'),ensure_ascii=False)
    json.dump(hist,open(HIST,'w'),ensure_ascii=False,indent=1)
    removed=[dict(id=k,**v) for k,v in hist.items() if not k.startswith('_') and v.get('removed')]
    try: prevfx=json.load(open(f"{SITE}/listings.json")).get('fx')
    except Exception: prevfx=None
    rate=fx(prevfx)
    areas=[]
    for city,names in [(k,v) for k,v in AREAS.items() if not k.startswith("_")]:
        for n in names:
            q=PREF[city]+n
            if q not in geo:
                try: r=S.get("https://msearch.gsi.go.jp/address-search/AddressSearch",params={'q':q},timeout=20).json(); geo[q]=r[0]['geometry']['coordinates'][::-1] if r else None
                except Exception: geo[q]=None
            if geo.get(q): areas.append(dict(city=city,name=n,lat=geo[q][0],lng=geo[q][1],radius_m=1500))
    json.dump(geo,open(GEO,'w'),ensure_ascii=False)
    data=dict(areas=areas,fx=rate,updated=datetime.datetime.now().strftime('%Y-%m-%d %H:%M CT'),sources=status,errors=errors,listings=cur,removed=removed)
    json.dump(data,open(f"{SITE}/listings.json",'w'),ensure_ascii=False,indent=1)
    from collections import Counter
    print("updated",data['updated']); print("per city",dict(Counter(L['city'] for L in cur)))
    print("match",sum(L['match'] for L in cur),"near",sum(L['near_match'] for L in cur),"new",sum(L['new'] for L in cur),"removed",len(removed))
    print("sources",status); print("errors",errors[:20])
