import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# テーマ設定と定数
USERNAME = "Swingray350"
# スクリプトの位置からリポジトリルートのassets配下へ出力する（実行ディレクトリ依存を防ぐ）
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "github-streak.svg"
N_SEGMENTS = 24


def _post_graphql(query: str, variables: dict[str, str], token: str) -> dict:
    """GitHub GraphQL APIへクエリを送信し、HTTPおよびGraphQLエラーを検証してdataを返す。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Swingray350-Profile-Generator",
    }
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(f"GitHub GraphQL API error: {payload['errors']}")
    return payload.get("data", {})


def fetch_contribution_days(username: str, token: str | None) -> list[tuple[str, int]]:
    """アカウント作成年から現在までの日別コントリビューション数を日付昇順で取得する。"""
    if not token:
        raise RuntimeError("GH_TOKEN environment variable is required to fetch GitHub streak.")

    created_query = """
    query($login: String!) {
      user(login: $login) {
        createdAt
      }
    }
    """
    created_data = _post_graphql(created_query, {"login": username}, token)
    user_info = created_data.get("user")
    if not user_info:
        raise RuntimeError(f"GitHub user not found: {username}")

    start_year = int(user_info["createdAt"][:4])
    now_utc = datetime.now(timezone.utc)
    end_year = now_utc.year
    today_str = now_utc.strftime("%Y-%m-%d")

    calendar_query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    day_map: dict[str, int] = {}
    for year in range(start_year, end_year + 1):
        data = _post_graphql(
            calendar_query,
            {
                "login": username,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{year}-12-31T23:59:59Z",
            },
            token,
        )
        weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        for week in weeks:
            for day in week["contributionDays"]:
                date_str = day["date"]
                # カレンダー末尾の未来日を含めるとCurrent Streak判定がずれるため今日までに制限する
                if date_str <= today_str:
                    day_map[date_str] = int(day["contributionCount"])

    return sorted(day_map.items(), key=lambda item: item[0])


def _format_span(start_str: str, end_str: str) -> str:
    """開始日・終了日の文字列を短い英語表記（例: Nov 24 - Nov 27）へ整形する。"""
    if not start_str or not end_str:
        return "-"
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    if start_str == end_str:
        return start_dt.strftime("%b %d")
    return f"{start_dt.strftime('%b %d')} - {end_dt.strftime('%b %d')}"


def calculate_streaks(days: list[tuple[str, int]]) -> dict[str, str | int]:
    """日別コントリビューション一覧からCurrent StreakとLongest Streakおよび期間を算出する。"""
    if not days:
        return {
            "current": 0,
            "longest": 0,
            "current_span": "No Active Streak",
            "longest_span": "-",
        }

    # 最長連続記録（Longest Streak）を全期間から走査する
    longest_streak = 0
    longest_start = ""
    longest_end = ""
    run = 0
    run_start = ""
    for date_str, count in days:
        if count > 0:
            if run == 0:
                run_start = date_str
            run += 1
            if run >= longest_streak:
                longest_streak = run
                longest_start = run_start
                longest_end = date_str
        else:
            run = 0

    # 現在継続中の連続記録（Current Streak）を末尾から遡る（今日が0でも昨日まで続いていれば継続扱い）
    idx = len(days) - 1
    if days[idx][1] == 0 and idx > 0 and days[idx - 1][1] > 0:
        idx -= 1

    current_streak = 0
    current_end = ""
    current_start = ""
    while idx >= 0 and days[idx][1] > 0:
        if current_streak == 0:
            current_end = days[idx][0]
        current_start = days[idx][0]
        current_streak += 1
        idx -= 1

    return {
        "current": current_streak,
        "longest": longest_streak,
        "current_span": _format_span(current_start, current_end) if current_streak > 0 else "No Active Streak",
        "longest_span": _format_span(longest_start, longest_end) if longest_streak > 0 else "-",
    }


def _unit_days(count: int) -> str:
    """単数・複数に応じたDAY/DAYSラベルを返す。"""
    return "DAY" if count == 1 else "DAYS"


def build_streak_svg(info: dict[str, str | int]) -> str:
    """Total Contributionsを除外したオーバードライブ・メーター風のStreak SVGを生成する。"""
    current = max(0, int(info["current"]))
    longest = max(0, int(info["longest"]))
    current_span = str(info["current_span"])
    longest_span = str(info["longest_span"])

    if longest > 0:
        ratio = min(1.0, current / longest)
        pct = min(100.0, (current / longest) * 100.0)
        lit_count = max(1, min(N_SEGMENTS, round(ratio * N_SEGMENTS))) if current > 0 else 0
    else:
        pct = 0.0
        lit_count = 0

    # ヘッダーステータス判定
    if current > 0 and current >= longest:
        status_color = "#f9f871"
        status_text = "OVERDRIVE MAX"
    elif current > 0:
        status_color = "#00ffb2"
        status_text = "COMBO ACTIVE"
    else:
        status_color = "#7928ca"
        status_text = "STANDBY"
    dot_x = round(536.0 - len(status_text) * 6.6 - 10.0, 1)

    # 24セグメントの斜めシェブロンチャージバー生成
    chevrons: list[str] = []
    clip_polys: list[str] = []
    for i in range(N_SEGMENTS):
        x0 = 24.0 + i * 21.2
        x1 = x0 + 16.5
        x2 = x1 + 5.0
        x3 = x0 + 5.0
        pts = f"{x3:.1f},78 {x2:.1f},78 {x1:.1f},102 {x0:.1f},102"
        if i < lit_count:
            if i < 8:
                col = "#00f2fe"
            elif i < 16:
                col = "#a855f7"
            else:
                col = "#ff007f"
            chevrons.append(f'  <polygon points="{pts}" fill="{col}" filter="url(#neon-glow)"/>')
            clip_polys.append(f'      <polygon points="{pts}"/>')
        else:
            chevrons.append(f'  <polygon points="{pts}" fill="#2a1650" opacity="0.8"/>')

    if lit_count > 0:
        end_x = round(24.0 + lit_count * 21.2 + 20.0, 1)
        clip_block = (
            '    <clipPath id="chev-clip">\n'
            + "\n".join(clip_polys)
            + "\n    </clipPath>"
        )
        pulse_block = (
            '  <!-- 点灯済みセグメントを自然な加減速で左→右へ走るエネルギーパルス -->\n'
            '  <g clip-path="url(#chev-clip)">\n'
            '    <rect x="-40" y="76" width="70" height="28" fill="url(#pulse-grad)">\n'
            f'      <animate attributeName="x" values="-40;{end_x};{end_x}" keyTimes="0;0.58;1" calcMode="spline" keySplines="0.4 0 0.2 1;0 0 1 1" dur="2.2s" repeatCount="indefinite" />\n'
            "    </rect>\n"
            "  </g>"
        )
    else:
        clip_block = ""
        pulse_block = ""

    # 右パネルの下段メッセージ（記録達成時はNEW RECORD!を強調表示）
    if current > 0 and current >= longest:
        right_value = "NEW RECORD!"
        right_color = "#f9f871"
        right_filter = ' filter="url(#neon-glow)"'
    else:
        remain = max(0, longest - current)
        right_value = f"{remain} {_unit_days(remain)} TO RECORD"
        right_color = "#00ffb2"
        right_filter = ""

    chevrons_block = "\n".join(chevrons)

    return f"""<svg width="560" height="195" viewBox="0 0 560 195" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- セグメント・数値・ランプにサイバーパンク風のネオン発光効果を与える -->
    <filter id="neon-glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.6" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <!-- 点灯中のシェブロンバー内を走る光の帯 -->
    <linearGradient id="pulse-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="50%" stop-color="#ffffff" stop-opacity="0.88"/>
      <stop offset="100%" stop-color="#00f2fe" stop-opacity="0"/>
    </linearGradient>
{clip_block}
  </defs>

  <!-- 外枠と背景 -->
  <rect x="0.5" y="0.5" width="559" height="194" rx="4.5" fill="#0d0221" stroke="#ff007f" stroke-width="1"/>

  <!-- ヘッダーと稼働ステータスランプ -->
  <text x="24" y="27" fill="#00f2fe" font-family="monospace" font-size="14" font-weight="bold">STREAK // OVERDRIVE METER</text>
  <circle cx="{dot_x}" cy="22" r="3.2" fill="{status_color}" filter="url(#neon-glow)">
    <animate attributeName="opacity" values="1;0.25;1" dur="1.4s" repeatCount="indefinite" />
  </circle>
  <text x="536" y="26" fill="{status_color}" font-family="monospace" font-size="11" font-weight="bold" text-anchor="end">{status_text}</text>

  <!-- メイン指標（Current Streak vs Target Record） -->
  <text x="24" y="63" fill="#ff007f" font-family="monospace" font-size="22" font-weight="bold" filter="url(#neon-glow)">CURRENT: {current} {_unit_days(current)}</text>
  <text x="536" y="62" fill="#00f2fe" font-family="monospace" font-size="13.5" font-weight="bold" text-anchor="end">TARGET RECORD: {longest} {_unit_days(longest)} ({pct:.0f}%)</text>

  <!-- 24セグメント斜めシェブロンチャージバー -->
{chevrons_block}
{pulse_block}

  <!-- 右端ゴールマーカー -->
  <line x1="536" y1="74" x2="536" y2="108" stroke="#00ffb2" stroke-width="1.5" stroke-dasharray="2 2"/>
  <text x="536" y="118" fill="#00ffb2" font-family="monospace" font-size="9" font-weight="bold" text-anchor="end">BEST</text>

  <!-- 下部2サブパネル（Total Contributionsを除外しStreak情報に特化） -->
  <rect x="24" y="130" width="248" height="48" rx="4" fill="#140630" stroke="#7928ca" stroke-width="1" stroke-opacity="0.7"/>
  <text x="148" y="147" fill="#7928ca" font-family="monospace" font-size="10.5" font-weight="bold" text-anchor="middle">CURRENT SPAN</text>
  <text x="148" y="168" fill="#e0e0e0" font-family="monospace" font-size="14" font-weight="bold" text-anchor="middle">{current_span}</text>

  <rect x="288" y="130" width="248" height="48" rx="4" fill="#140630" stroke="#7928ca" stroke-width="1" stroke-opacity="0.7"/>
  <text x="412" y="147" fill="#7928ca" font-family="monospace" font-size="10.5" font-weight="bold" text-anchor="middle">BEST: {longest_span}</text>
  <text x="412" y="168" fill="{right_color}" font-family="monospace" font-size="15" font-weight="bold" text-anchor="middle"{right_filter}>{right_value}</text>
</svg>
"""


def _build_mock_days() -> list[tuple[str, int]]:
    """ローカルプレビューテスト用の連続記録モック日別データを生成する。"""
    base = datetime(2026, 10, 1)
    days: list[tuple[str, int]] = []
    # 先頭24日間連続 + 1日間休止 + 直近12日間連続
    for i in range(37):
        d_str = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        count = 0 if i == 24 else 3
        days.append((d_str, count))
    return days


def main() -> None:
    """Streak統計を取得（またはモック使用）してSVGファイルを生成する。"""
    parser = argparse.ArgumentParser(description="Generate cyberpunk GitHub streak SVG.")
    parser.add_argument("--mock", action="store_true", help="Use dummy streak data for local preview.")
    args = parser.parse_args()

    if args.mock:
        days = _build_mock_days()
    else:
        token = os.environ.get("GH_TOKEN")
        days = fetch_contribution_days(USERNAME, token)

    info = calculate_streaks(days)
    svg_content = build_streak_svg(info)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)


if __name__ == "__main__":
    main()
