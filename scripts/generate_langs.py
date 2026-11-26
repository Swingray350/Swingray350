import math
import os
from pathlib import Path
from xml.sax.saxutils import escape

import requests

# テーマ設定と定数
USERNAME = "Swingray350"
# スクリプトの位置からリポジトリルートのassets配下へ出力する（実行ディレクトリ依存を防ぐ）
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "langs-spectrum.svg"
N_BARS = 90
MAX_SLICES = 5
NEON_PALETTE = ["#ff007f", "#00f2fe", "#00ffb2", "#a855f7", "#f9f871", "#ff6b35"]


def fetch_language_stats(username: str, token: str | None) -> dict[str, int]:
    """GitHub APIから各リポジトリの言語別バイト数を取得し合算する。"""
    if token:
        return _fetch_via_graphql(username, token)
    return _fetch_via_rest(username)


def _fetch_via_graphql(username: str, token: str) -> dict[str, int]:
    """GH_TOKENを利用してGraphQL APIから非フォークリポジトリの言語統計を一括取得する。"""
    query = """
    query($login: String!) {
      user(login: $login) {
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
          nodes {
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node {
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Swingray350-Profile-Generator",
    }
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": {"login": username}},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(f"GitHub GraphQL API error: {payload['errors']}")

    user_data = payload.get("data", {}).get("user")
    if not user_data:
        raise RuntimeError(f"GitHub user not found: {username}")

    totals: dict[str, int] = {}
    for repo in user_data["repositories"]["nodes"]:
        if not repo or not repo.get("languages"):
            continue
        for edge in repo["languages"]["edges"]:
            lang_name = edge["node"]["name"]
            totals[lang_name] = totals.get(lang_name, 0) + int(edge["size"])
    return totals


def _fetch_via_rest(username: str) -> dict[str, int]:
    """トークン未設定時のフォールバックとして公開REST APIから言語統計を取得する。"""
    headers = {"User-Agent": "Swingray350-Profile-Generator"}
    repos_resp = requests.get(
        f"https://api.github.com/users/{username}/repos?per_page=100",
        headers=headers,
        timeout=30,
    )
    repos_resp.raise_for_status()

    totals: dict[str, int] = {}
    for repo in repos_resp.json():
        if repo.get("fork"):
            continue
        lang_url = repo.get("languages_url")
        if not lang_url:
            continue
        lang_resp = requests.get(lang_url, headers=headers, timeout=30)
        lang_resp.raise_for_status()
        for lang_name, size in lang_resp.json().items():
            totals[lang_name] = totals.get(lang_name, 0) + int(size)
    return totals


def aggregate_languages(lang_bytes: dict[str, int]) -> list[tuple[str, int, float, str]]:
    """言語バイト数を上位5件+Otherに集約し、(言語名, バイト数, 割合%, カラー)のリストを返す。"""
    positive = [(name, size) for name, size in lang_bytes.items() if size > 0]
    if not positive:
        # 言語データが0件でもSVG描画が壊れないようフォールバックを返す
        return [("No Data", 1, 100.0, NEON_PALETTE[1])]

    positive.sort(key=lambda item: item[1], reverse=True)
    total_bytes = sum(size for _, size in positive)

    top_items = positive[:MAX_SLICES]
    other_bytes = sum(size for _, size in positive[MAX_SLICES:])
    if other_bytes > 0:
        top_items.append(("Other", other_bytes))

    result: list[tuple[str, int, float, str]] = []
    for idx, (name, size) in enumerate(top_items):
        pct = (size / total_bytes) * 100.0
        color = NEON_PALETTE[idx % len(NEON_PALETTE)]
        result.append((name, size, pct, color))
    return result


def allocate_bars(items: list[tuple[str, int, float, str]], total_bars: int = N_BARS) -> list[int]:
    """最大剰余法でスペクトラムバー合計本数を各言語へ配分する（割合>0は最低1本確保）。"""
    total_bytes = sum(size for _, size, _, _ in items)
    if total_bytes <= 0:
        return [total_bars]

    quotas = [(size / total_bytes) * total_bars for _, size, _, _ in items]
    counts = [max(1, math.floor(q)) for q in quotas]
    remainders = [q - math.floor(q) for q in quotas]

    # 最低1本確保による過不足を剰余の大小で調整し、合計を厳密にtotal_barsへ一致させる
    diff = total_bars - sum(counts)
    if diff > 0:
        order = sorted(range(len(items)), key=lambda i: remainders[i], reverse=True)
        for i in order[:diff]:
            counts[i] += 1
    elif diff < 0:
        order = sorted(range(len(items)), key=lambda i: remainders[i])
        for i in order:
            if diff == 0:
                break
            if counts[i] > 1:
                counts[i] -= 1
                diff += 1
    return counts


def _truncate(text: str, max_len: int) -> str:
    """指定文字数を超えるラベルを省略記号付きで短縮する。"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _pseudo_rand(seed: int) -> float:
    """環境間で再現可能な0.0以上1.0未満の擬似乱数を返す（オーディオスペクトラムのランダム性生成用）。"""
    x = math.sin(seed * 12.9898 + 78.233) * 43758.5453
    return x - math.floor(x)


def build_spectrum_svg(lang_bytes: dict[str, int]) -> str:
    """言語統計から動的オーディオスペクトラム風円グラフSVG文字列を生成する。"""
    items = aggregate_languages(lang_bytes)
    bar_counts = allocate_bars(items, N_BARS)

    cx, cy = 104, 132
    ring_r = 39
    circumference = 2.0 * math.pi * ring_r
    gap = 1.2 if len(items) > 1 else 0.0

    # 1. 内側ベースドーナツリング（12時方向から時計回りに各言語の円弧を描画）
    ring_segments: list[str] = []
    accumulated = 0.0
    for _, _, pct, color in items:
        arc_total = (pct / 100.0) * circumference
        seg_len = max(0.5, arc_total - gap)
        ring_segments.append(
            f'  <circle cx="{cx}" cy="{cy}" r="{ring_r}" fill="none" stroke="{color}" '
            f'stroke-width="4" stroke-dasharray="{seg_len:.2f} {circumference:.2f}" '
            f'stroke-dashoffset="{-accumulated:.2f}" transform="rotate(-90 {cx} {cy})" opacity="0.9"/>'
        )
        accumulated += arc_total

    # 2. 外側放射状オーディオスペクトラムバー（90本を4度刻みで配置）
    bar_colors: list[str] = []
    for (_, _, _, color), count in zip(items, bar_counts):
        bar_colors.extend([color] * count)

    bar_elements: list[str] = []
    for k, color in enumerate(bar_colors):
        angle = -90 + k * 4
        band = k // 3
        widths: list[str] = []
        for s in range(16):
            r_self = _pseudo_rand(k * 97 + s * 31 + 13)
            r_band = _pseudo_rand(band * 53 + s * 17 + 7)
            u = 0.72 * r_self + 0.28 * r_band
            if u > 0.78:
                # 音圧のピークらしい鋭いスパイクを外側へ突出させる
                raw_w = 18.0 + ((u - 0.78) / 0.22) * 7.0
            else:
                raw_w = 3.5 + (u ** 1.7) * 18.0
            w_s = round(max(3.5, min(25.0, raw_w)), 1)
            widths.append(f"{w_s}")
        # 始点と同じ値で終端を閉じることでループ継ぎ目のジャンプを防ぐ
        values_attr = ";".join(widths + [widths[0]])
        dur = round(0.62 + _pseudo_rand(k * 131 + 29) * 0.53, 2)
        begin_offset = round(_pseudo_rand(k * 71 + 41) * dur, 2)

        bar_elements.append(
            f'    <g transform="translate({cx},{cy}) rotate({angle})">\n'
            f'      <rect x="45" y="-0.85" width="{widths[0]}" height="1.7" rx="0.85" fill="{color}" opacity="0.92">\n'
            f'        <animate attributeName="width" values="{values_attr}" dur="{dur}s" begin="-{begin_offset}s" repeatCount="indefinite" />\n'
            f'      </rect>\n'
            f'    </g>'
        )

    # 3. 中央の最多言語サマリー
    top_name, _, top_pct, _ = items[0]
    top_label = escape(_truncate(top_name, 9))

    # 4. 右側の凡例リスト（縦中央揃え・文字サイズ拡大）
    m = len(items)
    start_y = cy - ((m - 1) * 28.0) / 2.0
    legend_elements: list[str] = []
    for idx, (name, _, pct, color) in enumerate(items):
        y = start_y + idx * 28.0
        label = escape(_truncate(name, 11))
        legend_elements.append(
            f'  <rect x="194" y="{y - 5.5:.1f}" width="10" height="10" rx="2.5" fill="{color}"/>\n'
            f'  <text x="211" y="{y + 4.5:.1f}" fill="#e0e0e0" font-family="monospace" font-size="14">{label}</text>\n'
            f'  <text x="382" y="{y + 4.5:.1f}" fill="{color}" font-family="monospace" font-size="14" font-weight="bold" text-anchor="end">{pct:.1f}%</text>'
        )

    rings_block = "\n".join(ring_segments)
    bars_block = "\n".join(bar_elements)
    legends_block = "\n".join(legend_elements)

    return f"""<svg width="400" height="230" viewBox="0 0 400 230" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- スペクトラムバーにサイバーパンク風のネオン発光効果を与える -->
    <filter id="neon-glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.2" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <!-- 外枠と背景（隣のGitHub Statsカードと統一した配色・角丸） -->
  <rect x="0.5" y="0.5" width="399" height="229" rx="4.5" fill="#0d0221" stroke="#ff007f" stroke-width="1"/>

  <!-- カードタイトル（隣のGitHub Statsカードと見出し位置・サイズを統一） -->
  <text x="18" y="29" fill="#00f2fe" font-family="monospace" font-size="16.5" font-weight="bold">Most Used Languages</text>

  <!-- 内側ベースドーナツリングと装飾点線リング -->
{rings_block}
  <circle cx="{cx}" cy="{cy}" r="31" fill="none" stroke="#7928ca" stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>

  <!-- 円中央の最多言語表示 -->
  <text x="{cx}" y="128" fill="#00f2fe" font-family="monospace" font-size="16.5" font-weight="bold" text-anchor="middle">{top_pct:.0f}%</text>
  <text x="{cx}" y="146" fill="#e0e0e0" font-family="monospace" font-size="11" text-anchor="middle" opacity="0.9">{top_label}</text>

  <!-- 外側放射状オーディオスペクトラムバー（90本・高速ランダム脈動） -->
  <g filter="url(#neon-glow)">
{bars_block}
  </g>

  <!-- 右側凡例リスト -->
{legends_block}
</svg>
"""


def main() -> None:
    """言語統計を取得して動的スペクトラムSVGファイルを生成する。"""
    token = os.environ.get("GH_TOKEN")
    lang_bytes = fetch_language_stats(USERNAME, token)
    svg_content = build_spectrum_svg(lang_bytes)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)


if __name__ == "__main__":
    main()
