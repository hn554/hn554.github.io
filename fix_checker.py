#!/usr/bin/env python3
"""index.html 프레임 이미지에 저장된 투명 배경 체크무늬 제거.

프레임 4개 중 3개(크림 도트, Worship Again, 꿈청 낙서)의 사진 영역에
디자인 툴의 투명 배경 체크무늬가 그대로 저장돼 있어, 합성 시 사진 위에
흰 격자가 나타난다. index.html 의 합성 로직은 사진을 먼저 그리고 프레임
PNG 를 그 위에 덮으므로(drawImage(frameImg, ...)), 프레임의 사진 영역이
불투명하면 그대로 사진을 가린다.

프레임마다 남은 형태가 달라 규칙을 나눈다:

  - 크림 도트(0): 사진 영역 안(흰 불투명+투명 교대) + 테두리 안쪽 띠
    (흰+회색 모두 불투명). 영역 안은 '밝은 무채색 불투명' 전부 제거,
    띠는 영역 경계에서 flood-fill 로 제거(검은 테두리·크림 배경에서 정지).
  - Worship Again(1): 사진 영역 안 전체가 체크무늬(종이 위 흰+투명 교대).
    영역 안 '밝은 무채색/미색 불투명' 전부 제거. 성경구절 텍스트(어두움)와
    별 낙서(유채색)는 조건에 안 걸려 보존.
  - 꿈청 낙서(2): 사진 영역에 알파 50 안팎의 흰 막이 깔리고 그 위에 격자선이
    얹혀 있어(합성 시 사진이 뿌옇게 뜨고 격자가 비친다) 0·1 과 같은 규칙으로
    전부 제거. 분홍 낙서(유채색)와 검은 테두리(어두움)는 보존된다.

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

LIGHT_MIN = 150      # '밝은' 판정: 모든 채널이 이 이상
NEUTRAL_MAX = 12     # '무채색' 판정: 채널 간 편차가 이 이하
ALPHA_KEEP = 10      # 이 이하 알파는 질감으로 보고 보존
FLOOD_MARGIN = 48    # flood-fill 이 셀 밖으로 나갈 수 있는 최대 거리

B64_RE = r'"data:image/png;base64,([A-Za-z0-9+/=]+)"'


def load_cells(html):
    """사진 영역 좌표를 index.html 의 CELLS 에서 직접 읽는다(좌표 이중 관리 방지)."""
    m = re.search(r"const\s+CELLS\s*=\s*(\[.*?\]);", html, re.S)
    if not m:
        sys.exit("CELLS array not found in index.html")
    literal = re.sub(r",(\s*[\]\}])", r"\1", m.group(1))  # 후행 쉼표 제거 → JSON 호환
    return json.loads(literal)


def neutral(p, wide_tint=False):
    r, g, b = p[:3]
    if min(r, g, b) < LIGHT_MIN:
        return False
    spread = max(r, g, b) - min(r, g, b)
    if spread <= NEUTRAL_MAX:
        return True
    # Worship Again 종이의 미색(살짝 따뜻한 흰색)까지 허용
    return wide_tint and min(r, g, b) >= 230 and spread <= 20


def clear_full(px, w, h, cells, wide_tint, flood):
    """사진 영역 안의 밝은 무채색 불투명 픽셀 전부 제거 (+ 선택적 띠 flood)."""
    cleared = 0
    for cx, cy, cw, ch in cells:
        x0, y0 = max(int(cx), 0), max(int(cy), 0)
        x1, y1 = min(int(cx + cw + 1), w), min(int(cy + ch + 1), h)
        for y in range(y0, y1):
            for x in range(x0, x1):
                p = px[x, y]
                if p[3] > ALPHA_KEEP and neutral(p, wide_tint):
                    px[x, y] = (p[0], p[1], p[2], 0)
                    cleared += 1
        if not flood:
            continue
        # 띠: 셀 경계에서 바깥으로 전파. 체크무늬(밝은 무채색)와 투명 픽셀로만
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
            if p[3] > ALPHA_KEEP and neutral(p, wide_tint):
                px[x, y] = (p[0], p[1], p[2], 0)
                cleared += 1
            elif p[3] > ALPHA_KEEP:
                continue  # 장식(어두움/유채색)에서 정지
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return cleared


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    cells = load_cells(html)
    uris = re.findall(B64_RE, html)
    if len(uris) != 4 or len(cells) != 4:
        sys.exit(f"expected 4 frames, found {len(uris)} images / {len(cells)} cell sets")

    plans = [
        (0, lambda px, w, h: clear_full(px, w, h, cells[0], False, flood=True)),
        (1, lambda px, w, h: clear_full(px, w, h, cells[1], True, flood=False)),
        (2, lambda px, w, h: clear_full(px, w, h, cells[2], False, flood=False)),
    ]
    for fi, run in plans:
        im = Image.open(io.BytesIO(base64.b64decode(uris[fi]))).convert("RGBA")
        cleared = run(im.load(), *im.size)
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
