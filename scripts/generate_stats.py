import argparse
import math
import os
from pathlib import Path

import requests

# テーマ設定と定数
USERNAME = "Swingray350"
# スクリプトの位置からリポジトリルートのassets配下へ出力する（実行ディレクトリ依存を防ぐ）
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "github-stats.svg"

# ランク算出用の加重パラメータ (重み, 中央値)
RANK_WEIGHTS: dict[str, tuple[float, float]] = {
    "commits": (2.0, 250.0),
    "prs": (3.0, 50.0),
    "issues": (1.0, 25.0),
    "stars": (4.0, 50.0),
    "contributed": (1.0, 10.0),
}

# プレビュー・ローカルテスト用のダミーデータ
MOCK_STATS: dict[str, int] = {
    "stars": 18,
    "commits": 164,
    "prs": 27,
    "issues": 14,
    "contributed": 9,
}


def fetch_github_stats(username: str, token: str | None) -> dict[str, int]:
    """GitHub GraphQL APIからプロフィール統計（Stars/Commits/PRs/Issues/Contributed）を取得する。"""
    if not token:
        raise RuntimeError("GH_TOKEN environment variable is required to fetch GitHub stats.")

    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
        pullRequests(first: 1) {
          totalCount
        }
        issues(first: 1) {
          totalCount
        }
        repositoriesContributedTo(
          first: 1
          contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
        ) {
          totalCount
        }
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
          nodes {
            stargazerCount
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

    contrib = user_data["contributionsCollection"]
    commits = int(contrib["totalCommitContributions"]) + int(contrib["restrictedContributionsCount"])
    stars = sum(int(node["stargazerCount"]) for node in user_data["repositories"]["nodes"] if node)

    return {
        "stars": stars,
        "commits": commits,
        "prs": int(user_data["pullRequests"]["totalCount"]),
        "issues": int(user_data["issues"]["totalCount"]),
        "contributed": int(user_data["repositoriesContributedTo"]["totalCount"]),
    }


def calculate_rank(stats: dict[str, int]) -> tuple[str, float]:
    """各統計値の加重達成率からランク文字列と達成度（0.0〜1.0）を算出する。"""
    weighted_sum = 0.0
    total_weight = 0.0
    for key, (weight, median) in RANK_WEIGHTS.items():
        val = max(0, int(stats.get(key, 0)))
        score = val / (val + median) if val > 0 else 0.0
        weighted_sum += weight * score
        total_weight += weight

    progress = weighted_sum / total_weight if total_weight > 0 else 0.0
    progress = max(0.0, min(1.0, progress))

    if progress < 0.25:
        rank = "C"
    elif progress < 0.45:
        rank = "B"
    elif progress < 0.65:
        rank = "B+"
    elif progress < 0.80:
        rank = "A"
    elif progress < 0.90:
        rank = "A+"
    elif progress < 0.96:
        rank = "S"
    else:
        rank = "S+"

    return rank, progress


def _calc_axis_max(actual_max: int) -> int:
    """横棒グラフのX軸上限値を、データ最大値に応じて見やすいキリの良い数値に切り上げる。"""
    if actual_max <= 10:
        return 10
    if actual_max <= 50:
        return math.ceil(actual_max / 10) * 10
    if actual_max <= 200:
        return math.ceil(actual_max / 20) * 20
    return math.ceil(actual_max / 50) * 50


def build_stats_svg(stats: dict[str, int]) -> str:
    """横軸棒グラフと扇型ランクゲージ（針付き）を備えたサイバーパンク風Stats SVGを生成する。"""
    rank, progress = calculate_rank(stats)

    # 左側：横軸棒グラフの定義
    bar_specs = [
        ("STARS", max(0, int(stats.get("stars", 0))), "#f9f871", 58),
        ("COMMITS", max(0, int(stats.get("commits", 0))), "#00f2fe", 90),
        ("PRs", max(0, int(stats.get("prs", 0))), "#ff007f", 122),
        ("ISSUES", max(0, int(stats.get("issues", 0))), "#a855f7", 154),
        ("CONTRIB", max(0, int(stats.get("contributed", 0))), "#00ffb2", 186),
    ]
    actual_max = max(val for _, val, _, _ in bar_specs)
    axis_max = _calc_axis_max(actual_max)
    track_x = 18.0
    track_w = 248.0

    bar_elements: list[str] = []
    clip_defs: list[str] = []
    for idx, (label, val, color, y) in enumerate(bar_specs):
        bar_w = round(max(4.0, (val / axis_max) * track_w), 1) if val > 0 else 0.0
        bar_y = y + 6
        # セグメント刻み線（25%, 50%, 75%）を重ねてデジタル計器感を出す
        ticks_x = [track_x + track_w * frac for frac in (0.25, 0.5, 0.75)]
        tick_lines = "\n".join(
            f'  <line x1="{tx:.1f}" y1="{bar_y}" x2="{tx:.1f}" y2="{bar_y + 7}" stroke="#0d0221" stroke-width="1" opacity="0.85"/>'
            for tx in ticks_x
        )
        if bar_w > 0:
            clip_defs.append(
                f'    <clipPath id="clip-bar-{idx}"><rect x="{track_x:.0f}" y="{bar_y}" width="{bar_w}" height="7" rx="3.5"/></clipPath>'
            )
            end_x = round(track_x + bar_w + 4.0, 1)
            delay = round(idx * 0.25, 2)
            bar_rect = (
                f'  <rect x="{track_x:.0f}" y="{bar_y}" width="{bar_w}" height="7" rx="3.5" fill="{color}" filter="url(#neon-glow)"/>\n'
                f'  <g clip-path="url(#clip-bar-{idx})">\n'
                f'    <rect x="-18" y="{bar_y}" width="36" height="7" fill="url(#pulse-grad)">\n'
                f'      <animate attributeName="x" values="-18;{end_x};{end_x}" keyTimes="0;0.58;1" calcMode="spline" keySplines="0.4 0 0.2 1;0 0 1 1" dur="2.4s" begin="{delay}s" repeatCount="indefinite" />\n'
                f"    </rect>\n"
                f"  </g>"
            )
        else:
            bar_rect = ""
        bar_elements.append(
            f'  <text x="18" y="{y}" fill="#e0e0e0" font-family="monospace" font-size="14">{label}</text>\n'
            f'  <text x="266" y="{y}" fill="{color}" font-family="monospace" font-size="14" font-weight="bold" text-anchor="end">{val}</text>\n'
            f'  <rect x="{track_x:.0f}" y="{bar_y}" width="{track_w:.0f}" height="7" rx="3.5" fill="#2a1650" opacity="0.75"/>\n'
            f"{bar_rect}\n"
            f"{tick_lines}"
        )

    # 右側：240度扇型ランクゲージと針の定義
    cx, cy = 370, 138
    gauge_r = 58.0
    circumference = 2.0 * math.pi * gauge_r
    arc_240 = circumference * (240.0 / 360.0)
    fill_len = max(0.0, min(arc_240, arc_240 * progress))

    # 扇型周囲の放射状目盛り（-120度〜+120度を10度刻みで25本描画）
    gauge_ticks: list[str] = []
    for deg in range(-120, 121, 10):
        rad = math.radians(deg - 90)
        is_major = deg in (-120, -60, 0, 60, 120)
        r_in = 64.0 if is_major else 65.0
        r_out = 71.0 if is_major else 69.0
        x1 = cx + r_in * math.cos(rad)
        y1 = cy + r_in * math.sin(rad)
        x2 = cx + r_out * math.cos(rad)
        y2 = cy + r_out * math.sin(rad)
        stroke = "#00f2fe" if is_major else "#7928ca"
        sw = "1.5" if is_major else "1"
        op = "" if is_major else ' opacity="0.85"'
        gauge_ticks.append(
            f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{op}/>'
        )

    # 外周のランクラベル（C, B, A, S, S+）
    rank_labels_spec = [(-120, "C"), (-60, "B"), (0, "A"), (60, "S"), (120, "S+")]
    rank_labels: list[str] = []
    for deg, lbl in rank_labels_spec:
        rad = math.radians(deg - 90)
        lx = cx + 80.0 * math.cos(rad)
        ly = cy + 80.0 * math.sin(rad)
        rank_labels.append(
            f'  <text x="{lx:.1f}" y="{ly:.1f}" fill="#e0e0e0" font-family="monospace" font-size="10.5" font-weight="bold" text-anchor="middle" dominant-baseline="central">{lbl}</text>'
        )

    # アナログ計器のように目標角度付近で大きく不規則にぐらつく針（イーズインアウト加減速付き）
    needle_angle = -120.0 + progress * 240.0
    deltas = (0.0, 5.2, -3.5, 6.0, -2.2, 3.4, -4.5, 2.0, 0.0)
    angles = [round(max(-120.0, min(120.0, needle_angle + d)), 2) for d in deltas]
    needle_values = ";".join(f"{a}" for a in angles)
    needle_key_times = "0;0.11;0.24;0.39;0.52;0.66;0.80;0.91;1"
    needle_key_splines = ";".join(["0.42 0 0.58 1"] * 8)

    clips_block = "\n".join(clip_defs)
    bars_block = "\n".join(bar_elements)
    ticks_block = "\n".join(gauge_ticks)
    labels_block = "\n".join(rank_labels)

    return f"""<svg width="465" height="230" viewBox="0 0 465 230" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- 棒グラフ・ゲージ・針にサイバーパンク風のネオン発光効果を与える -->
    <filter id="neon-glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.6" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <!-- 扇型ゲージの低ランクから高ランクにかけてネオン色を遷移させる -->
    <linearGradient id="gauge-grad" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#7928ca"/>
      <stop offset="50%" stop-color="#00f2fe"/>
      <stop offset="100%" stop-color="#ff007f"/>
    </linearGradient>
    <!-- バー内部を左から右へ駆け抜けるエネルギーパルス用の光の帯 -->
    <linearGradient id="pulse-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="50%" stop-color="#ffffff" stop-opacity="0.88"/>
      <stop offset="100%" stop-color="#00f2fe" stop-opacity="0"/>
    </linearGradient>
{clips_block}
  </defs>

  <!-- 外枠と背景（隣のMost Used Languagesカードと高さ・角丸・配色を統一） -->
  <rect x="0.5" y="0.5" width="464" height="229" rx="4.5" fill="#0d0221" stroke="#ff007f" stroke-width="1"/>

  <!-- カードタイトル -->
  <text x="18" y="29" fill="#00f2fe" font-family="monospace" font-size="16.5" font-weight="bold">{USERNAME}'s GitHub Stats</text>

  <!-- 左側：項目ごとの横棒グラフ -->
{bars_block}

  <!-- 横棒グラフのX軸ラインと目盛り -->
  <line x1="18" y1="207" x2="266" y2="207" stroke="#7928ca" stroke-width="1" opacity="0.8"/>
  <text x="18" y="221" fill="#7928ca" font-family="monospace" font-size="10.5" text-anchor="start">0</text>
  <text x="142" y="221" fill="#7928ca" font-family="monospace" font-size="10.5" text-anchor="middle">{axis_max // 2}</text>
  <text x="266" y="221" fill="#7928ca" font-family="monospace" font-size="10.5" text-anchor="end">{axis_max}</text>

  <!-- 右側：240度扇型ランクゲージ（背景アークと達成度アーク） -->
  <circle cx="{cx}" cy="{cy}" r="{gauge_r:.0f}" fill="none" stroke="#2a1650" stroke-width="8.5" stroke-linecap="round" stroke-dasharray="{arc_240:.2f} {circumference:.2f}" transform="rotate(150 {cx} {cy})"/>
  <circle cx="{cx}" cy="{cy}" r="{gauge_r:.0f}" fill="none" stroke="url(#gauge-grad)" stroke-width="8.5" stroke-linecap="round" filter="url(#neon-glow)" stroke-dasharray="{fill_len:.2f} {circumference:.2f}" transform="rotate(150 {cx} {cy})"/>

  <!-- 扇型ゲージ周囲の目盛りとランク文字 -->
{ticks_block}
{labels_block}

  <!-- 外周目盛りを自然な加減速で走査するスキャン輝線 -->
  <g transform="translate({cx},{cy})">
    <line x1="0" y1="-63" x2="0" y2="-72" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" filter="url(#neon-glow)">
      <animateTransform attributeName="transform" type="rotate" values="-120;120" keyTimes="0;1" calcMode="spline" keySplines="0.45 0.05 0.55 0.95" dur="2.8s" repeatCount="indefinite" />
      <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.88;1" dur="2.8s" repeatCount="indefinite" />
    </line>
  </g>

  <!-- 達成度を示す針（目標位置付近で自然な加減速で大きくぐらつく計器演出） -->
  <g transform="translate({cx},{cy})">
    <g transform="rotate({angles[0]})">
      <polygon points="0,-53 -3.2,8 0,12 3.2,8" fill="#ff007f" filter="url(#neon-glow)"/>
      <animateTransform attributeName="transform" type="rotate" values="{needle_values}" keyTimes="{needle_key_times}" calcMode="spline" keySplines="{needle_key_splines}" dur="3.6s" repeatCount="indefinite" />
    </g>
  </g>
  <circle cx="{cx}" cy="{cy}" r="6" fill="#00f2fe"/>
  <circle cx="{cx}" cy="{cy}" r="2.8" fill="#0d0221"/>

  <!-- 扇型下部のランク・達成度サマリー -->
  <text x="{cx}" y="186" fill="#00f2fe" font-family="monospace" font-size="18.5" font-weight="bold" text-anchor="middle" filter="url(#neon-glow)">RANK {rank}</text>
  <text x="{cx}" y="206" fill="#ff007f" font-family="monospace" font-size="12" font-weight="bold" text-anchor="middle">{progress * 100:.1f}%</text>
</svg>
"""


def main() -> None:
    """統計データを取得（またはモック使用）してGitHub Stats SVGファイルを生成する。"""
    parser = argparse.ArgumentParser(description="Generate cyberpunk GitHub stats SVG.")
    parser.add_argument("--mock", action="store_true", help="Use dummy stats for local preview.")
    args = parser.parse_args()

    if args.mock:
        stats = dict(MOCK_STATS)
    else:
        token = os.environ.get("GH_TOKEN")
        stats = fetch_github_stats(USERNAME, token)

    svg_content = build_stats_svg(stats)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)


if __name__ == "__main__":
    main()
