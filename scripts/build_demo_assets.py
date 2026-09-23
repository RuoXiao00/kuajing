"""生成仓库自带的原创 SVG 商品/场景示意图，不抓取图片、不使用私人生成历史。

运行 python scripts/build_demo_assets.py；正常构建直接使用已提交的 public/demo 文件。
这些是程序绘制的插画，不是 Coze / AI 输出，也不代表真实商品。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'public' / 'demo'
SHAPES = {
    'bottle': '<rect x="176" y="113" width="88" height="50" rx="12" fill="#384c42"/><rect x="162" y="154" width="116" height="164" rx="30" fill="url(#product)"/><rect x="173" y="211" width="94" height="59" rx="2" fill="#f8f4e9"/><text x="220" y="237" text-anchor="middle" fill="#54604e" font-size="14" letter-spacing="4">FORM</text><path d="M199 248h42" stroke="#aaa58e"/><path d="M185 172v26" stroke="#fff" stroke-opacity=".5" stroke-width="5" stroke-linecap="round"/>',
    'headphones': '<path d="M130 240V182a90 90 0 0 1 180 0v58" fill="none" stroke="#475a50" stroke-width="25"/><path d="M143 180a77 77 0 0 1 154 0" fill="none" stroke="#9caf9b" stroke-width="9"/><rect x="111" y="204" width="60" height="103" rx="28" fill="url(#product)"/><rect x="269" y="204" width="60" height="103" rx="28" fill="url(#product)"/><path d="M162 224v63m116-63v63" stroke="#314137" stroke-width="12" stroke-linecap="round"/>',
    'lamp': '<ellipse cx="220" cy="322" rx="77" ry="12" fill="#506455"/><path d="M220 194v126" stroke="#455b4b" stroke-width="13"/><path d="M169 120h102l59 104H110z" fill="url(#product)"/><ellipse cx="220" cy="224" rx="110" ry="14" fill="#e1d7b9"/><ellipse cx="220" cy="224" rx="45" ry="6" fill="#fff8da"/>',
    'bag': '<path d="M171 173v-22a49 49 0 0 1 98 0v22" fill="none" stroke="#7e8570" stroke-width="15"/><path d="M132 169h176l20 147H112z" fill="url(#product)"/><path d="M132 177l15 129h149l12-129" fill="none" stroke="#aebba5" stroke-width="2"/><rect x="185" y="223" width="70" height="46" rx="4" fill="#ebe5d3"/><text x="220" y="249" text-anchor="middle" font-size="12" fill="#647259" letter-spacing="2">EVERYDAY</text>',
    'blocks': '<rect x="123" y="224" width="94" height="93" rx="9" fill="#9baf98"/><rect x="224" y="224" width="94" height="93" rx="9" fill="#ddbb99"/><path d="M145 217l72-101 71 101z" fill="#718974"/><circle cx="276" cy="184" r="32" fill="#e5d3b4"/><circle cx="166" cy="270" r="23" fill="#c2ccad"/>',
    'organizer': '<path d="M101 165h238v139H101z" fill="url(#product)"/><path d="M101 165l38-37h162l38 37z" fill="#b0bca5"/><path d="M107 171h226m-147 0v126m70-126v126" stroke="#e1e7d8" stroke-width="5"/><rect x="125" y="205" width="39" height="8" rx="4" fill="#536c58"/><rect x="199" y="205" width="39" height="8" rx="4" fill="#536c58"/><rect x="272" y="205" width="39" height="8" rx="4" fill="#536c58"/>',
    'cup': '<path d="M160 144h120l-13 171h-94z" fill="url(#product)"/><rect x="153" y="129" width="134" height="26" rx="8" fill="#44584b"/><path d="M183 186h75l-5 81h-64z" fill="#d4ddc7"/><text x="220" y="234" text-anchor="middle" fill="#4c644e" font-size="14" letter-spacing="3">SLOW</text>',
    'backpack': '<path d="M193 133v-15h54v15" fill="none" stroke="#3b5142" stroke-width="12"/><rect x="137" y="131" width="166" height="190" rx="45" fill="url(#product)"/><rect x="161" y="219" width="118" height="80" rx="17" fill="#6e866c"/><path d="M170 239h100M178 162h84" stroke="#d5dcc9" stroke-width="5" stroke-linecap="round"/><path d="M137 171l-18 97m184-97l18 97" stroke="#455e4d" stroke-width="12" stroke-linecap="round"/>',
}


def draw(name, background='#f3f0e7', scene=0):
    decor = ''
    if scene == 2:
        decor = '<path d="M0 0h90l240 440H230zM160 0h55l225 415v25h-44z" fill="#fff7da" opacity=".65"/>'
    if scene == 3:
        decor = '<g fill="#6f8a6d" opacity=".25"><ellipse cx="36" cy="100" rx="72" ry="25" transform="rotate(35 36 100)"/><ellipse cx="393" cy="260" rx="77" ry="30" transform="rotate(-35 393 260)"/></g>'
    if scene == 4:
        decor = '<path d="M260 58h180v300H260z" fill="#d7c5af"/><circle cx="358" cy="145" r="80" fill="#eee1cd"/>'
    pedestal = '<path d="M117 331h206v109H117z" fill="#dedace"/><ellipse cx="220" cy="331" rx="103" ry="20" fill="#f9f5ec"/>' if scene else ''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="880" viewBox="0 0 440 440" role="img" aria-label="原创产品场景示意图">
<defs><linearGradient id="product" x1="0" x2="1"><stop stop-color="#bcc8ab"/><stop offset=".5" stop-color="#8da586"/><stop offset="1" stop-color="#5c755b"/></linearGradient><filter id="blur"><feGaussianBlur stdDeviation="9"/></filter></defs>
<rect width="440" height="440" fill="{background}"/>{decor}{pedestal}<ellipse cx="225" cy="329" rx="90" ry="14" fill="#293c2a" opacity=".13" filter="url(#blur)"/>{SHAPES[name]}
<text x="26" y="36" fill="#657462" font-family="sans-serif" font-size="10" letter-spacing="3">FORM / STUDY {scene or '01'}</text><text x="26" y="416" fill="#75816b" font-family="sans-serif" font-size="9" letter-spacing="2">KUAIJING · DEMO ILLUSTRATION</text></svg>'''


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in SHAPES:
        (ROOT / f'{name}.svg').write_text(draw(name), encoding='utf-8')
    for i, color in enumerate(('#f4f2eb', '#ede0c8', '#dce6d6', '#e8dfd4'), 1):
        (ROOT / f'scene-{i}.svg').write_text(draw('bottle', color, i), encoding='utf-8')
    print('Created 12 original demo illustrations.')
