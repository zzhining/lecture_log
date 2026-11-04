#!/usr/bin/env python3
"""PDF 강의자료를 '디자인 그대로 + 등장 애니메이션' 슬라이드 html 로 변환한다.

사용법:  python scripts/pdf_to_slides.py temp/파일.pdf [출력폴더=agent] [--title "제목"]

방식
- 각 페이지에서 텍스트만 제거한 그림(도형/이미지/만화 포함)을 배경 webp 로 렌더링
- 텍스트는 원본 위치/크기/색 그대로 html 로 얹어 블록 단위로 순서대로 등장시킴
- 결과: <출력폴더>/<파일명>.html + <출력폴더>/<파일명>/NN.webp
"""
import html, io, json, re, sys
from pathlib import Path
import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STAGE_H = 900
RENDER = 1.5          # 스테이지 대비 배경 이미지 해상도 배율

def keep_in_bg(span):
    f = span["font"].lower()
    return "wingding" in f or "symbol" in f or any(0xE000 <= ord(c) <= 0xF8FF for c in span["text"])

def weight(font):
    f = font.lower()
    if "bold" in f or "black" in f or "heavy" in f: return 700
    if "medium" in f: return 500
    if "light" in f or "thin" in f: return 300
    return 400

def convert(pdf, outdir, title=None):
    pdf = Path(pdf); outdir = Path(outdir)
    slug = pdf.stem
    assets = outdir / slug
    assets.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    pw, ph = doc[0].rect.width, doc[0].rect.height
    k = STAGE_H / ph
    W, H = round(pw * k), STAGE_H
    slides = []
    for i, page in enumerate(doc, 1):
        d = page.get_text("rawdict")
        blocks, redact, alphas = [], [], []
        for b in d["blocks"]:
            if b["type"] != 0: continue
            lines = []
            for l in b["lines"]:
                dx, dy = l["dir"]
                for s in l["spans"]:
                    s["text"] = "".join(c["c"] for c in s["chars"])
                    if not s["text"].strip() or keep_in_bg(s):
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    redact.append(pymupdf.Rect(x0, y0, x1, y1))
                    alphas.append(s.get("alpha", 255))
                    # 글자 위치 기준으로 단어 단위 분할 (PDF 에 공백 문자가 없어도 원본 간격 유지)
                    runs, cur = [], []
                    for c in s["chars"]:
                        if not c["c"].strip():
                            if cur: runs.append(cur); cur = []
                            continue
                        if cur and c["bbox"][0] - cur[-1]["bbox"][2] > 0.18 * s["size"]:
                            runs.append(cur); cur = []
                        cur.append(c)
                    if cur: runs.append(cur)
                    for r in runs:
                        rx0, rx1 = r[0]["bbox"][0], r[-1]["bbox"][2]
                        lines.append(dict(t="".join(c["c"] for c in r), x=rx0*k, y=y0*k, w=(rx1-rx0)*k,
                                          h=(y1-y0)*k, fs=s["size"]*k, c="#%06x" % s["color"],
                                          fw=weight(s["font"]), it=bool(s["flags"] & 2),
                                          rot=(dx, dy) != (1.0, 0.0)))
            if lines: blocks.append(lines)
        # 보이지 않는(alpha=0) 글자층 + 글자가 이미지로 그려진 PDF: 원본 렌더에서 영역을 잘라 등장시킨다
        crop = bool(alphas) and sum(1 for a in alphas if a == 0) > len(alphas) / 2
        mat = pymupdf.Matrix(RENDER * k, RENDER * k)
        def save(pm, name):
            Image.frombytes("RGB", (pm.width, pm.height), pm.samples).save(assets / name, "WEBP", quality=84, method=4)
        if crop:
            save(page.get_pixmap(matrix=mat, alpha=False), f"{i:02d}_full.webp")
        # 글자 위에 겹쳐 깔린 초소형(≤4px) 효과 이미지는 글자 잔상이 되므로 제거
        dead = set()
        for im in page.get_images(full=True):
            xr = im[0]
            if im[2] <= 4 and im[3] <= 4:
                for r in page.get_image_rects(xr):
                    ar = r.get_area() or 1
                    if any((r & t).get_area() / ar > 0.6 for t in redact): dead.add(xr); break
        for xr in dead: page.delete_image(xr)
        for r in redact: page.add_redact_annot(r, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        save(page.get_pixmap(matrix=mat, alpha=False), f"{i:02d}.webp")
        slides.append((blocks, crop))
        if i == 1 and not title:
            spans = [s for b in blocks for s in b]
            title = max(spans, key=lambda s: s["fs"])["t"].strip() if spans else slug
    return slug, title, slides, W, H

def render_html(slug, title, slides, W, H):
    out = []
    for i, (blocks, crop) in enumerate(slides, 1):
        n = len(blocks)
        step = min(0.14, 2.0 / max(n, 1))
        parts = [f'<img class="bg" src="{slug}/{i:02d}.webp" alt="" decoding="async">']
        for j, b in enumerate(blocks):
            d = min(0.35 + j * step, 3.0)
            if crop:
                P, PX = 4, 18   # 글자 효과/자간이 투명 글자층보다 넓게 그려지므로 가로 여백을 더 둔다
                x0 = min(t["x"] for t in b) - PX; y0 = min(t["y"] for t in b) - P
                x1 = max(t["x"] + t["w"] for t in b) + PX; y1 = max(t["y"] + t["h"] for t in b) + P
                x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                parts.append(f'<div class="a" style="--d:{d:.2f}s"><i class="cr" style="left:{x0:.1f}px;top:{y0:.1f}px;'
                             f'width:{x1-x0:.1f}px;height:{y1-y0:.1f}px;background-position:{-x0:.1f}px {-y0:.1f}px"></i></div>')
                continue
            sp = []
            for s in b:
                st = (f"left:{s['x']:.1f}px;top:{s['y']:.1f}px;height:{s['h']:.1f}px;line-height:{s['h']:.1f}px;"
                      f"font-size:{s['fs']:.1f}px;color:{s['c']};font-weight:{s['fw']}"
                      + (";font-style:italic" if s["it"] else ""))
                sp.append(f'<span class="t" data-w="{s["w"]:.1f}" style="{st}">{html.escape(s["t"])}</span>')
            parts.append(f'<div class="a" style="--d:{d:.2f}s">{"".join(sp)}</div>')
        sty = f' style="--full:url({slug}/{i:02d}_full.webp)"' if crop else ""
        out.append(f'<section class="slide"{sty}>{"".join(parts)}</section>')
    body = "\n".join(out)
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__W__", str(W)).replace("__H__", str(H)) \
                   .replace("__SLIDES__", body)

TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
:root{--ease:cubic-bezier(.2,.75,.2,1)}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;background:#0B1119}
body{font-family:'Pretendard','Malgun Gothic','Noto Sans KR',sans-serif;-webkit-font-smoothing:antialiased}
#vp{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 50% 40%,#18222F 0%,#0B1119 70%)}
#stage{position:relative;width:__W__px;height:__H__px;flex:none;transform-origin:center center;box-shadow:0 30px 80px rgba(0,0,0,.45);background:#fff}
.slide{position:absolute;inset:0;overflow:hidden;background:#fff;opacity:0;visibility:hidden;transition:opacity .5s ease,visibility 0s .5s}
.slide.cur{opacity:1;visibility:visible;transition:opacity .5s ease,visibility 0s}
.bg{position:absolute;inset:0;width:100%;height:100%;display:block;opacity:0;transform:scale(1.025);transition:opacity .8s ease,transform 1.1s var(--ease)}
.on .bg{opacity:1;transform:none}
.a{position:absolute;inset:0;pointer-events:none;opacity:0;transform:translateY(18px);filter:blur(4px);
   transition:opacity .65s var(--ease),transform .8s var(--ease),filter .65s ease;transition-delay:var(--d,0s)}
.on .a{opacity:1;transform:none;filter:none}
.t{position:absolute;white-space:pre;transform-origin:0 50%}
.cr{position:absolute;display:block;background-image:var(--full);background-size:__W__px __H__px;background-repeat:no-repeat}
#prog{position:fixed;left:0;right:0;bottom:0;height:3px;background:rgba(255,255,255,.12);z-index:5}
#prog i{display:block;height:100%;width:0;background:#E8402F;transition:width .5s var(--ease)}
#hint{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);color:#cbd5e1;font-size:13px;background:rgba(0,0,0,.55);
      padding:6px 14px;border-radius:99px;z-index:5;transition:opacity .6s}
#hint.hide{opacity:0}
#grid{position:fixed;inset:0;background:rgba(8,12,18,.96);z-index:9;display:none;overflow:auto;padding:24px;
      grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;align-content:start}
#grid.show{display:grid}
.th{position:relative;aspect-ratio:__W__/__H__;overflow:hidden;cursor:pointer;border:2px solid transparent;background:#fff}
.th.cur{border-color:#E8402F}
.th .slide{opacity:1;visibility:visible;transform-origin:0 0;width:__W__px;height:__H__px}
.th .n{position:absolute;right:6px;bottom:4px;background:rgba(0,0,0,.6);color:#fff;font:600 12px sans-serif;padding:1px 7px;border-radius:9px}
</style></head><body>
<div id="vp"><div id="stage">
__SLIDES__
</div></div>
<div id="prog"><i></i></div>
<div id="hint">← → 이동 · F 전체화면 · G 목차</div>
<div id="grid"></div>
<script>
(function(){
const W=__W__,H=__H__;
const stage=document.getElementById('stage'),slides=[...stage.querySelectorAll('.slide')],N=slides.length;
const prog=document.querySelector('#prog i'),hint=document.getElementById('hint'),grid=document.getElementById('grid');
function fitText(root){
  root.querySelectorAll('.t').forEach(e=>{
    e.style.transform='';
    const w=+e.dataset.w,nw=e.offsetWidth;
    if(nw>0&&w>0){const r=Math.max(.5,Math.min(1.6,w/nw));if(Math.abs(r-1)>.02)e.style.transform='scaleX('+r.toFixed(3)+')';}
  });
}
function fit(){const s=Math.min(innerWidth/W,innerHeight/H);stage.style.transform='scale('+s+')';}
addEventListener('resize',fit);fit();
(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(()=>fitText(stage));
let cur=-1;
function go(n){
  n=Math.max(0,Math.min(N-1,n));if(n===cur)return;
  const p=slides[cur];if(p)p.classList.remove('cur','on');
  const s=slides[n];s.classList.add('cur');
  requestAnimationFrame(()=>requestAnimationFrame(()=>s.classList.add('on')));
  cur=n;prog.style.width=((n+1)/N*100)+'%';history.replaceState(null,'','#'+(n+1));
}
const next=()=>go(cur+1),prev=()=>go(cur-1);
addEventListener('keydown',e=>{
  if(grid.classList.contains('show')){if(e.key==='Escape'||e.key==='g'||e.key==='G')toggleGrid();return;}
  if(['ArrowRight','PageDown',' ','Enter','ArrowDown'].includes(e.key)){next();e.preventDefault();}
  else if(['ArrowLeft','PageUp','Backspace','ArrowUp'].includes(e.key)){prev();e.preventDefault();}
  else if(e.key==='Home')go(0);else if(e.key==='End')go(N-1);
  else if(e.key==='f'||e.key==='F'){document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();}
  else if(e.key==='g'||e.key==='G')toggleGrid();
});
document.getElementById('vp').addEventListener('click',e=>{if(getSelection().toString())return;(e.clientX<innerWidth*.3)?prev():next();});
let tx=null;addEventListener('touchstart',e=>tx=e.touches[0].clientX,{passive:true});
addEventListener('touchend',e=>{if(tx===null)return;const dx=e.changedTouches[0].clientX-tx;if(Math.abs(dx)>40)(dx<0?next:prev)();tx=null;});
let built=false;
function toggleGrid(){
  if(!built){
    slides.forEach((s,i)=>{const t=document.createElement('div');t.className='th';const c=s.cloneNode(true);
      c.classList.add('on');c.classList.remove('cur');t.appendChild(c);
      const b=document.createElement('b');b.className='n';b.textContent=i+1;t.appendChild(b);
      t.onclick=()=>{toggleGrid();go(i);};grid.appendChild(t);});
    built=true;
  }
  const show=!grid.classList.contains('show');grid.classList.toggle('show',show);
  if(show){[...grid.children].forEach((t,i)=>{t.classList.toggle('cur',i===cur);const sc=t.clientWidth/W;
      t.firstChild.style.transform='scale('+sc+')';t.querySelectorAll('.a,.bg').forEach(x=>x.style.transition='none');});
    grid.children[cur].scrollIntoView({block:'center'});}
}
setTimeout(()=>hint.classList.add('hide'),5000);
go(Math.max(0,(parseInt(location.hash.slice(1))||1)-1));
})();
</script></body></html>
"""

def main():
    args = [a for a in sys.argv[1:]]
    title = None
    if "--title" in args:
        i = args.index("--title"); title = args[i + 1]; del args[i:i + 2]
    if not args: sys.exit(__doc__)
    outdir = Path(args[1]) if len(args) > 1 else ROOT / "agent"
    slug, title, slides, W, H = convert(args[0], outdir, title)
    (outdir / f"{slug}.html").write_text(render_html(slug, title, slides, W, H), encoding="utf-8", newline="\n")
    print(f"{slug}.html: {len(slides)} slides ({sum(1 for _, c in slides if c)} crop-mode), {sum(len(b) for b, _ in slides)} text blocks, stage {W}x{H}, title={title!r}")

if __name__ == "__main__":
    main()
