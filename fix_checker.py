#!/usr/bin/env python3
"""index.html 프레임 이미지에 저장된 투명 배경 체크무늬 제거.

프레임 4개 중 3개(크림 도트, Worship Again, 꿈청 낙서)의 사진 영역에
디자인 툴의 투명 배경 체크무늬가 그대로 저장돼 있어, 합성 시 사진 위에
흰 격자가 나타난다. index.html 의 합성 로직은 사진을 먼저 그리고 프레임
PNG 를 그 위에 덮으므로(drawImage(frameImg, ...)), 프레임의 사진 영역이
불투명하면 그대로 사진을 가린다.

남은 형태는 프레임마다 다르다:

  - 크림 도트(0): 흰 불투명+투명 교대. 사진 영역 밖 테두리 안쪽 띠까지
    번져 있어 flood-fill 로 함께 제거(검은 테두리·크림 배경에서 정지).
  - Worship Again(1): 종이 위 흰+투명 교대가 사진 영역 전체에.
  - 꿈청 낙서(2): 알파 50 안팎의 흰 막 + 그 위의 격자선. 합성하면 사진이
    뿌옇게 뜨고 격자가 비친다. 격자가 순수 회색이 아니라 연분홍 색조
    (예: 218,190,200)를 띠어서, 무채색만 지우는 규칙으로는 살아남았다.

판정은 is_wash() 한 곳 — '밝고 채도가 낮으면' 지운다. 낙서·글씨·테두리는
어둡거나 채도가 높아(0.3~0.7) 조건에 안 걸려 보존된다.

보라 글로우(3)는 정상이라 건드리지 않는다.

이미 적용된 index.html 에 다시 돌려도 지울 픽셀이 없어 결과가 바뀌지 않는다.

사용법: python3 fix_checker.py   (실행 위치 무관, Pillow 필요)
"""
import base64
import io
import json
import re
import sys
from collections import deque
from pathlib import Path

from PIL import Image

HTML_PATH = Path(__file__).resolve().parent / "index.html"

# 지울 것(체크무늬·흰 막·격자)은 '밝고 채도가 낮다'. 남길 것(낙서·글씨·테두리)은
# '어둡거나 채도가 높다'. 순수 무채색만 지우면 연분홍 색조(예: 218,190,200)를 띤
# 격자가 살아남으므로 채도로 판정한다.
LIGHT_MIN_LUM = 150  # '밝은' 판정: 평균 밝기가 이 이상
SAT_MAX = 0.25       # '색이 옅은' 판정: 채도가 이 이하 (낙서는 0.3~0.7)
ALPHA_KEEP = 10      # 이 이하 알파는 질감으로 보고 보존
FLOOD_MARGIN = 48    # flood-fill 이 셀 밖으로 나갈 수 있는 최대 거리

# Worship Again(1) 아래쪽 별 뭉치 재배치
STAR_BOX = (281, 431, 382, 541)   # 원래 자리 (사진 위에 얹혀 있음)
STAR_SCALE = 0.70
STAR_AT = (311, 295)              # 옮길 자리 — 왼쪽 말씀 구절과 같은 줄

B64_RE = r'"data:image/png;base64,([A-Za-z0-9+/=]+)"'


def load_rects(html, name):
    """좌표를 index.html 에서 직접 읽는다(좌표 이중 관리 방지)."""
    m = re.search(r"const\s+" + name + r"\s*=\s*(\[.*?\]);", html, re.S)
    if not m:
        sys.exit(f"{name} array not found in index.html")
    literal = re.sub(r"//[^\n]*", "", m.group(1))         # 줄 주석 제거
    literal = re.sub(r",(\s*[\]\}])", r"\1", literal)     # 후행 쉼표 제거 → JSON 호환
    return json.loads(literal)


def is_wash(p):
    """체크무늬·흰 막·격자면 True. 낙서/글씨/테두리면 False."""
    r, g, b, a = p
    if a <= ALPHA_KEEP:
        return False
    if (r + g + b) / 3 < LIGHT_MIN_LUM:
        return False
    mx = max(r, g, b)          # 밝기 조건을 통과했으므로 mx > 0
    return (mx - min(r, g, b)) / mx <= SAT_MAX


def clear_full(px, w, h, cells, flood, inset=0):
    """사진 영역 안의 흰 막/체크무늬 전부 제거 (+ 선택적 띠 flood).
    inset 을 주면 구멍 가장자리를 그만큼 남긴다 — 테두리가 부드럽게
    번지는 프레임(보라 글로우)에서 경계가 거칠어지지 않도록."""
    cleared = 0
    for cx, cy, cw, ch in cells:
        x0, y0 = max(int(cx + inset), 0), max(int(cy + inset), 0)
        x1, y1 = min(int(cx + cw + 1 - inset), w), min(int(cy + ch + 1 - inset), h)
        for y in range(y0, y1):
            for x in range(x0, x1):
                p = px[x, y]
                if is_wash(p):
                    px[x, y] = (p[0], p[1], p[2], 0)
                    cleared += 1
        if not flood:
            continue
        # 띠: 셀 경계에서 바깥으로 전파. 체크무늬와 투명 픽셀로만
        # 나아가고, 검은 테두리·크림 배경(유채색)에서 멈춘다.
        bx0, by0 = max(x0 - FLOOD_MARGIN, 0), max(y0 - FLOOD_MARGIN, 0)
        bx1, by1 = min(x1 + FLOOD_MARGIN, w), min(y1 + FLOOD_MARGIN, h)
        seen = set()
        q = deque()
        for x in range(x0, x1):
            q.append((x, y0 - 1)); q.append((x, y1))
        for y in range(y0, y1):
            q.append((x0 - 1, y)); q.append((x1, y))
        while q:
            x, y = q.popleft()
            if not (bx0 <= x < bx1 and by0 <= y < by1) or (x, y) in seen:
                continue
            seen.add((x, y))
            p = px[x, y]
            if is_wash(p):
                px[x, y] = (p[0], p[1], p[2], 0)
                cleared += 1
            elif p[3] > ALPHA_KEEP:
                continue  # 장식(어두움/유채색)에서 정지
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return cleared


def move_star(im):
    """Worship Again(1): 아래쪽 별 뭉치가 사진 위에 얹혀 인물을 가린다.
    왼쪽 말씀 구절과 같은 줄(사진 영역 위)로 축소 이동해 좌우 균형을 맞춘다.
    STAR_BOX 안에는 별 픽셀만 있고 옮길 자리는 비어 있음을 확인했다."""
    sprite = im.crop(STAR_BOX)
    px = im.load()
    x0, y0, x1, y1 = STAR_BOX
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (r, g, b, 0)
    w, h = sprite.size
    sprite = sprite.resize((round(w * STAR_SCALE), round(h * STAR_SCALE)), Image.LANCZOS)
    im.alpha_composite(sprite, STAR_AT)
    return sprite.size


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    # 지우는 범위는 구멍 전체(OPENINGS). 사진을 그리는 CELLS 보다 넓을 수 있다
    openings = load_rects(html, "OPENINGS")
    uris = re.findall(B64_RE, html)
    if len(uris) != 4 or len(openings) != 4:
        sys.exit(f"expected 4 frames, found {len(uris)} images / {len(openings)} openings")

    # (프레임, flood, inset)
    # 0: 테두리 안쪽 띠까지 번져 있어 flood 필요
    # 3: 사진 위에 흰 반점이 흩뿌려져 있다. 구멍 경계는 파란 배경(채도 높음)이
    #    받쳐주므로 가장자리까지 지워도 테두리가 무너지지 않는다
    plans = [(0, True, 0), (1, False, 0), (2, False, 0), (3, False, 0)]
    for fi, flood, inset in plans:
        im = Image.open(io.BytesIO(base64.b64decode(uris[fi]))).convert("RGBA")
        w, h = im.size
        cleared = clear_full(im.load(), w, h, openings[fi], flood, inset)
        if fi == 1:
            print(f"frame1: 별 이동/축소 → {move_star(im)}")
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        html = html.replace(
            f'"data:image/png;base64,{uris[fi]}"',
            f'"data:image/png;base64,{new_b64}"',
        )
        print(f"frame{fi}: cleared {cleared} checker pixels, "
              f"{len(uris[fi])//1024}KB -> {len(new_b64)//1024}KB (base64)")

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"{HTML_PATH.name} updated")


if __name__ == "__main__":
    main()
