import argparse
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# テーマ設定と定数
USERNAME = "Swingray350"
# スクリプトの位置からリポジトリルートのassets配下へ出力する（実行ディレクトリ依存を防ぐ）
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "total-contributions.svg"

# プロット領域の固定座標（確定デザイン goal-04-checkpoints.svg を厳密に維持）
PLOT_X_START = 40.0
PLOT_X_END = 280.0
PLOT_Y_TOP = 48.0
PLOT_Y_BOTTOM = 168.0
PLOT_WIDTH = PLOT_X_END - PLOT_X_START
PLOT_HEIGHT = PLOT_Y_BOTTOM - PLOT_Y_TOP
Y_TICK_DIVISIONS = 5
MAX_CURVE_SEGMENTS = 20

# 3次ベジェ1セグメントの型（x0, y0, c1x, c1y, c2x, c2y, x1, y1）
BezierSegment = tuple[float, float, float, float, float, float, float, float]


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


def fetch_contribution_history(username: str, token: str | None) -> tuple[str, list[tuple[str, int]]]:
    """アカウント作成日と全期間の日別コントリビューション数（日付昇順）を取得する。"""
    if not token:
        raise RuntimeError("GH_TOKEN environment variable is required to fetch GitHub contributions.")

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

    created_at_str = str(user_info["createdAt"])
    created_date_str = created_at_str[:10]
    start_year = int(created_date_str[:4])
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
                # カレンダー末尾の未来日を除外し、今日までの実績に限定する
                if date_str <= today_str:
                    day_map[date_str] = int(day["contributionCount"])

    sorted_days = sorted(day_map.items(), key=lambda item: item[0])

    # アカウント作成日以前の不要な0区間を省きつつ、インポート等で作成日前に実績がある場合は保持する
    nonzero_dates = [d for d, count in sorted_days if count > 0]
    effective_start = min(created_date_str, nonzero_dates[0]) if nonzero_dates else created_date_str
    filtered_days = [(d, count) for d, count in sorted_days if d >= effective_start]

    return effective_start, filtered_days


def calculate_goals(total: int) -> tuple[int, list[int]]:
    """総コントリビューション数から次のGOAL値と通過済み過去GOAL一覧を算出する（初回100、以降500刻み）。"""
    safe_total = max(0, total)
    if safe_total < 100:
        return 100, []
    next_goal = ((safe_total // 500) + 1) * 500
    past_goals = [100] + list(range(500, next_goal, 500))
    return next_goal, past_goals


def _format_tick_label(value: int) -> str:
    """縦軸目盛りラベルを整形する（10,000以上は枠収まりのためk表記にする）。"""
    if value >= 10000 and value % 1000 == 0:
        return f"{value // 1000}k"
    return str(value)


def _build_monotone_bezier_segments(points: list[tuple[float, float]]) -> tuple[str, list[BezierSegment]]:
    """Fritsch-Carlsonの単調3次エルミート補間でSVGベジェパスとセグメント制御点一覧を生成する。"""
    n = len(points)
    if n == 0:
        return f"M {PLOT_X_START:.1f} {PLOT_Y_BOTTOM:.1f}", []
    if n == 1:
        x0, y0 = points[0]
        return f"M {x0:.1f} {y0:.1f}", []
    if n == 2:
        (x0, y0), (x1, y1) = points
        c1x = x0 + (x1 - x0) / 3.0
        c1y = y0 + (y1 - y0) / 3.0
        c2x = x1 - (x1 - x0) / 3.0
        c2y = y1 - (y1 - y0) / 3.0
        seg: BezierSegment = (x0, y0, c1x, c1y, c2x, c2y, x1, y1)
        return f"M {x0:.1f} {y0:.1f} C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {x1:.1f} {y1:.1f}", [seg]

    h: list[float] = []
    delta: list[float] = []
    for i in range(n - 1):
        dx = points[i + 1][0] - points[i][0]
        dy = points[i + 1][1] - points[i][1]
        h.append(dx)
        delta.append(dy / dx if dx != 0.0 else 0.0)

    m: list[float] = [0.0] * n
    m[0] = delta[0]
    m[-1] = delta[-1]
    for i in range(1, n - 1):
        if delta[i - 1] == 0.0 or delta[i] == 0.0 or (delta[i - 1] * delta[i] < 0.0):
            m[i] = 0.0
        else:
            m[i] = (delta[i - 1] + delta[i]) * 0.5

    # 単調性を保つため接線傾きを半径3の円内にクランプする
    for i in range(n - 1):
        if delta[i] == 0.0:
            m[i] = 0.0
            m[i + 1] = 0.0
        else:
            alpha = m[i] / delta[i]
            beta = m[i + 1] / delta[i]
            norm_sq = alpha * alpha + beta * beta
            if norm_sq > 9.0:
                tau = 3.0 / math.sqrt(norm_sq)
                m[i] = tau * alpha * delta[i]
                m[i + 1] = tau * beta * delta[i]

    commands = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    segments: list[BezierSegment] = []
    for i in range(n - 1):
        x_i, y_i = points[i]
        x_next, y_next = points[i + 1]
        step_x = h[i] / 3.0
        c1x = x_i + step_x
        c1y = y_i + m[i] * step_x
        c2x = x_next - step_x
        c2y = y_next - m[i + 1] * step_x
        commands.append(f"C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {x_next:.1f} {y_next:.1f}")
        segments.append((x_i, y_i, c1x, c1y, c2x, c2y, x_next, y_next))

    return " ".join(commands), segments


def _find_curve_x_at_y(segments: list[BezierSegment], target_y: float) -> float | None:
    """単調非増加（SVG上で右肩上がり）の3次ベジェ曲線群から指定Y座標との交点Xを二分探索で求める。"""
    for x0, y0, c1x, c1y, c2x, c2y, x1, y1 in segments:
        # 浮動小数点誤差を吸収しつつ、最初に対象Yを横切るセグメントを特定する
        if target_y <= y0 + 1e-6 and target_y >= y1 - 1e-6:
            if abs(y0 - y1) < 1e-9:
                return x0
            lo = 0.0
            hi = 1.0
            for _ in range(50):
                t = (lo + hi) * 0.5
                u = 1.0 - t
                y = (u * u * u * y0) + (3.0 * u * u * t * c1y) + (3.0 * u * t * t * c2y) + (t * t * t * y1)
                if y > target_y:
                    lo = t
                else:
                    hi = t
            t_final = (lo + hi) * 0.5
            u_final = 1.0 - t_final
            return (
                (u_final * u_final * u_final * x0)
                + (3.0 * u_final * u_final * t_final * c1x)
                + (3.0 * u_final * t_final * t_final * c2x)
                + (t_final * t_final * t_final * x1)
            )
    return None


def build_cumulative_series(start_date: str, days: list[tuple[str, int]]) -> dict[str, object]:
    """日別コントリビューション配列から累積推移・総数・開始日ラベル（YYYY/MM/DD）を算出する。"""
    if len(start_date) >= 10:
        start_date_label = start_date[:10].replace("-", "/")
    else:
        start_date_label = datetime.now(timezone.utc).strftime("%Y/%m/%d")

    cumulative: list[int] = []
    running = 0
    for _, count in days:
        running += max(0, int(count))
        cumulative.append(running)

    total = cumulative[-1] if cumulative else 0
    return {
        "start_date_label": start_date_label,
        "total": total,
        "cumulative": cumulative,
    }


def build_total_contributions_svg(series_info: dict[str, object]) -> str:
    """チェックポイント型のTotal Contributions SVGを生成する（確定デザイン・アニメーションを厳密維持）。"""
    start_date_label = str(series_info["start_date_label"])
    total = max(0, int(series_info["total"]))
    cumulative = list(series_info["cumulative"])  # type: ignore[arg-type]

    next_goal, past_goals = calculate_goals(total)
    y_max = next_goal
    step = y_max // Y_TICK_DIVISIONS
    remaining = max(0, next_goal - total)

    # 基本5等分の目盛り値（上: y_max から 下: 0 まで6個）
    tick_values = [step * (Y_TICK_DIVISIONS - i) for i in range(Y_TICK_DIVISIONS + 1)]
    tick_ys = [PLOT_Y_TOP + (PLOT_HEIGHT / Y_TICK_DIVISIONS) * i for i in range(Y_TICK_DIVISIONS + 1)]
    past_goal_set = set(past_goals)
    tick_value_set = set(tick_values)

    # 水平グリッド線の構築（最上段は現在GOAL緑破線、過去GOALと重なる紫破線は後段の緑破線に譲る）
    grid_lines: list[str] = []
    for i, (val, gy) in enumerate(zip(tick_values, tick_ys)):
        if i == 0:
            grid_lines.append(
                f'  <line x1="40" y1="{gy:.1f}" x2="282" y2="{gy:.1f}" stroke="#00ffb2" stroke-opacity="0.6" stroke-dasharray="6,3" stroke-width="1"/>'
            )
        elif i == Y_TICK_DIVISIONS:
            grid_lines.append(
                f'  <line x1="40" y1="{gy:.1f}" x2="282" y2="{gy:.1f}" stroke="#7928ca" stroke-opacity="0.5" stroke-width="1"/>'
            )
        elif val not in past_goal_set:
            grid_lines.append(
                f'  <line x1="40" y1="{gy:.1f}" x2="282" y2="{gy:.1f}" stroke="#7928ca" stroke-opacity="0.25" stroke-dasharray="2,3" stroke-width="0.8"/>'
            )

    # 過去GOALの緑横線と右端ラベル（降順で配置し、将来件数が増えてもラベル同士・X軸と重ならないよう調整）
    past_goal_lines: list[str] = []
    placed_label_ys: list[float] = []
    for g in reversed(past_goals):
        gy = PLOT_Y_BOTTOM - (g / y_max) * PLOT_HEIGHT
        past_goal_lines.append(
            f'  <line x1="40" y1="{gy:.1f}" x2="282" y2="{gy:.1f}" stroke="#00ffb2" stroke-opacity="0.45" stroke-dasharray="6,3" stroke-width="0.9"/>'
        )
        candidate_y = gy + 8.5 if gy + 8.5 <= 166.5 else gy - 2.5
        if all(abs(candidate_y - prev_y) >= 9.0 for prev_y in placed_label_ys):
            past_goal_lines.append(
                f'  <text x="280" y="{candidate_y:.1f}" text-anchor="end" font-family="monospace" font-size="7.5" fill="#00ffb2" opacity="0.75">GOAL {g}</text>'
            )
            placed_label_ys.append(candidate_y)

    # 縦軸ティック（現在GOAL・過去GOAL位置は緑、通常目盛りは紫）
    tick_marks: list[tuple[float, str]] = []
    for i, (val, gy) in enumerate(zip(tick_values, tick_ys)):
        if i == 0 or val in past_goal_set:
            tick_marks.append((gy, f'    <line x1="37" y1="{gy:.1f}" x2="40" y2="{gy:.1f}" stroke="#00ffb2" stroke-opacity="0.8"/>'))
        else:
            tick_marks.append((gy, f'    <line x1="37" y1="{gy:.1f}" x2="40" y2="{gy:.1f}"/>'))
    for g in past_goals:
        if g not in tick_value_set:
            gy = PLOT_Y_BOTTOM - (g / y_max) * PLOT_HEIGHT
            tick_marks.append((gy, f'    <line x1="37" y1="{gy:.1f}" x2="40" y2="{gy:.1f}" stroke="#00ffb2" stroke-opacity="0.8"/>'))
    tick_marks.sort(key=lambda item: item[0])
    tick_marks_block = "\n".join(line for _, line in tick_marks)

    # 縦軸ラベル（上端GOALは緑太字、過去GOALと一致する目盛りは緑、他は通常色）
    y_labels: list[str] = []
    for i, (val, gy) in enumerate(zip(tick_values, tick_ys)):
        label = _format_tick_label(val)
        ly = gy + 3.0
        if i == 0:
            y_labels.append(f'    <text x="35" y="{ly:.1f}" fill="#00ffb2" font-weight="bold">{label}</text>')
        elif val in past_goal_set:
            y_labels.append(f'    <text x="35" y="{ly:.1f}" fill="#00ffb2">{label}</text>')
        else:
            y_labels.append(f'    <text x="35" y="{ly:.1f}">{label}</text>')
    y_labels_block = "\n".join(y_labels)

    # 曲線用サンプル点の構築（始点は必ず (40.0, 168.0)、終点は必ず (280.0, end_y)）
    if not cumulative or total == 0:
        points = [(PLOT_X_START, PLOT_Y_BOTTOM), (PLOT_X_END, PLOT_Y_BOTTOM)]
    else:
        total_days = len(cumulative)
        num_segments = min(MAX_CURVE_SEGMENTS, max(1, total_days))
        points = [(PLOT_X_START, PLOT_Y_BOTTOM)]
        for k in range(1, num_segments + 1):
            x_val = PLOT_X_START + PLOT_WIDTH * (k / num_segments)
            if k == num_segments:
                cum_val = total
            else:
                idx = min(total_days - 1, round((total_days - 1) * (k / num_segments)))
                cum_val = cumulative[idx]
            y_val = PLOT_Y_BOTTOM - (cum_val / y_max) * PLOT_HEIGHT
            points.append((x_val, y_val))

    end_y = points[-1][1]
    curve_d, segments = _build_monotone_bezier_segments(points)
    area_d = f"{curve_d} L {PLOT_X_END:.1f} {PLOT_Y_BOTTOM:.1f} L {PLOT_X_START:.1f} {PLOT_Y_BOTTOM:.1f} Z"

    # 過去GOAL位置とカーブの交点に配置する通過済みチェックポイントダイヤ
    checkpoint_rects: list[str] = []
    for g in past_goals:
        gy = PLOT_Y_BOTTOM - (g / y_max) * PLOT_HEIGHT
        gx = _find_curve_x_at_y(segments, gy)
        if gx is not None:
            checkpoint_rects.append(
                f'      <rect x="-3.2" y="-3.2" width="6.4" height="6.4" transform="translate({gx:.1f} {gy:.1f}) rotate(45)" fill="#00ffb2" stroke="#0d0221" stroke-width="1" filter="url(#glow-cyan-4)"/>'
            )
    if checkpoint_rects:
        checkpoints_block = (
            '    <!-- 通過済みチェックポイント（過去のGOAL）：エリアと同じクリップで、カーブが通過した瞬間に出現する -->\n'
            '    <g clip-path="url(#area-reveal)">\n'
            + "\n".join(checkpoint_rects)
            + "\n    </g>"
        )
    else:
        checkpoints_block = ""

    # 終点から次のチェックポイントへの点線（十分な距離がある場合のみ描画しGOAL直前の重なりを防ぐ）
    connector_y1 = end_y - 6.3
    connector_y2 = PLOT_Y_TOP + 6.0
    if connector_y1 > connector_y2 + 1.0:
        connector_block = (
            '    <!-- 終点から次のチェックポイントへの点線（到達後に表示） -->\n'
            f'    <line x1="280" y1="{connector_y1:.1f}" x2="280" y2="{connector_y2:.1f}" stroke="#00ffb2" stroke-width="1" stroke-dasharray="1.5,2" opacity="0">\n'
            '      <animate attributeName="opacity" values="0;0;0.9;0.9" keyTimes="0;0.48;0.55;1" dur="6s" repeatCount="indefinite"/>\n'
            "    </line>"
        )
    else:
        connector_block = ""

    grid_block = "\n".join(grid_lines)
    past_goal_block = (
        "\n  <!-- 過去のGOAL位置：緑の横線として明示する -->\n" + "\n".join(past_goal_lines)
        if past_goal_lines
        else ""
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="300" height="195" viewBox="0 0 300 195">
  <defs>
    <filter id="glow-cyan-4" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.6" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <filter id="glow-pink-4" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ff007f" stop-opacity="0.45"/>
      <stop offset="60%" stop-color="#7928ca" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#00f2fe" stop-opacity="0.03"/>
    </linearGradient>
    <!-- スキャナーの縦の光の帯（幅0の line だと objectBoundingBox のグラデーションが描画されないため、細い rect で描く） -->
    <linearGradient id="scan-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#00f2fe" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="#00f2fe" stop-opacity="0"/>
    </linearGradient>
    <!-- エリアの塗りを線の描画と同期して左から表示する -->
    <clipPath id="area-reveal">
      <rect x="40" y="44" width="242" height="126">
        <animate attributeName="width" values="0;0;242;242" keyTimes="0;0.05;0.45;1" calcMode="spline" keySplines="0 0 1 1;0.45 0 0.25 1;0 0 1 1" dur="6s" repeatCount="indefinite"/>
      </rect>
    </clipPath>
    <!-- スキャナーの帯を X 軸（y=168）で切る -->
    <clipPath id="plot-clip">
      <rect x="0" y="44" width="300" height="124"/>
    </clipPath>
  </defs>

  <!-- 外枠・背景 -->
  <rect x="0.5" y="0.5" width="299" height="194" rx="4.5" fill="#0d0221" stroke="#ff007f" stroke-width="1"/>

  <!-- ヘッダー（STREAKと色・サイズ・Y位置を統一） -->
  <text x="16" y="27" fill="#00f2fe" font-family="monospace" font-size="14" font-weight="bold">TOTAL CONTRIBUTIONS</text>

  <!-- 水平グリッド線（0〜{y_max} を y=168〜48 に対応させる。5等分＝24px） -->
{grid_block}{past_goal_block}

  <!-- 縦軸と目盛り -->
  <line x1="40" y1="48" x2="40" y2="168" stroke="#7928ca" stroke-opacity="0.5" stroke-width="1"/>
  <g stroke="#7928ca" stroke-opacity="0.6" stroke-width="1">
{tick_marks_block}
  </g>
  <g font-family="monospace" font-size="8.5" fill="#9a8ec4" text-anchor="end">
{y_labels_block}
  </g>

  <!-- 総数（プロット左上の空いた領域に置き、罫線と重ねる） -->
  <text x="50" y="90" font-family="monospace" font-size="38" font-weight="bold" fill="#00f2fe" filter="url(#glow-cyan-4)">{total}</text>
  <!-- 終点に到達した瞬間に総数が一瞬光る -->
  <text x="50" y="90" font-family="monospace" font-size="38" font-weight="bold" fill="#ffffff" opacity="0" filter="url(#glow-cyan-4)">{total}<animate attributeName="opacity" values="0;0;0.55;0;0" keyTimes="0;0.44;0.47;0.62;1" dur="6s" repeatCount="indefinite"/></text>

  <!-- 次のチェックポイント（GOAL {next_goal}）：未達成なので中空のダイヤを点滅させる -->
  <rect x="-4" y="-4" width="8" height="8" transform="translate(280 48) rotate(45)" fill="#0d0221" stroke="#00ffb2" stroke-width="1.3">
    <animate attributeName="opacity" values="1;0.3;1" keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="1.6s" repeatCount="indefinite"/>
  </rect>
  <text x="270" y="43" text-anchor="end" font-family="monospace" font-size="10.5" font-weight="bold" fill="#00ffb2">NEXT {next_goal} // {remaining} LEFT</text>

  <!-- チャートレイヤー（周期の終わりにまとめてフェードアウトし、空の状態から再描画することで継ぎ目なくループさせる） -->
  <g>
    <animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.82;0.95;1" calcMode="spline" keySplines="0 0 1 1;0.42 0 0.58 1;0 0 1 1" dur="6s" repeatCount="indefinite"/>

    <!-- 累積エリアの塗り -->
    <path d="{area_d}" fill="url(#area-grad)" clip-path="url(#area-reveal)"/>

    <!-- 累積カーブ（dasharray のギャップを120にするのは、offset=101 のときに次の dash が終端に現れないようにするため） -->
    <path id="curve-line" d="{curve_d}" fill="none" stroke="#ff007f" stroke-width="2" stroke-linecap="round" pathLength="100" stroke-dasharray="100 120" stroke-dashoffset="0">
      <animate attributeName="stroke-dashoffset" values="101;101;0;0" keyTimes="0;0.05;0.45;1" calcMode="spline" keySplines="0 0 1 1;0.45 0 0.25 1;0 0 1 1" dur="6s" repeatCount="indefinite"/>
    </path>

{checkpoints_block}
{connector_block}

    <!-- 到達時の波紋リング -->
    <circle cx="280" cy="{end_y:.1f}" r="3.5" fill="none" stroke="#ff007f" stroke-width="1.5" opacity="0">
      <animate attributeName="r" values="3.5;3.5;16;16" keyTimes="0;0.45;0.66;1" calcMode="spline" keySplines="0 0 1 1;0.2 0.6 0.35 1;0 0 1 1" dur="6s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0;0;0.9;0;0" keyTimes="0;0.44;0.46;0.66;1" dur="6s" repeatCount="indefinite"/>
    </circle>

    <!-- 最新地点（終点）のドット：到達後に表示して呼吸させる -->
    <g opacity="1">
      <animate attributeName="opacity" values="0;0;1;1" keyTimes="0;0.44;0.47;1" dur="6s" repeatCount="indefinite"/>
      <circle cx="280" cy="{end_y:.1f}" r="7" fill="#ff007f" opacity="0.35">
        <animate attributeName="r" values="4;9;4" keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="1.8s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.6;0.1;0.6" keyTimes="0;0.5;1" dur="1.8s" repeatCount="indefinite"/>
      </circle>
      <circle cx="280" cy="{end_y:.1f}" r="3.5" fill="#ff007f" stroke="#ffffff" stroke-width="1" filter="url(#glow-pink-4)"/>
    </g>
  </g>

  <!-- 描画中の線の先端を追うスキャナーヘッド（親 g の clip は静止座標なので、帯は常に X 軸で切れる） -->
  <g clip-path="url(#plot-clip)">
    <g opacity="0">
      <animateMotion dur="6s" repeatCount="indefinite" keyPoints="0;0;1;1" keyTimes="0;0.05;0.45;1" calcMode="spline" keySplines="0 0 1 1;0.45 0 0.25 1;0 0 1 1">
        <mpath xlink:href="#curve-line"/>
      </animateMotion>
      <animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;0.04;0.07;0.43;0.47;1" dur="6s" repeatCount="indefinite"/>
      <rect x="-0.6" y="0" width="1.2" height="122" fill="url(#scan-grad)"/>
      <circle r="5.5" fill="#00f2fe" opacity="0.3"/>
      <circle r="2.8" fill="#ffffff" stroke="#00f2fe" stroke-width="1.2" filter="url(#glow-cyan-4)"/>
    </g>
  </g>

  <!-- 下部軸ラベル -->
  <text x="40" y="182" font-family="monospace" font-size="9.5" fill="#9a8ec4">{start_date_label}</text>
  <text x="175" y="182" text-anchor="middle" font-family="monospace" font-size="9" fill="#7928ca">CUMULATIVE GROWTH</text>
  <text x="282" y="182" text-anchor="end" font-family="monospace" font-size="9.5" font-weight="bold" fill="#00f2fe">NOW</text>
</svg>
"""


def _build_mock_history() -> tuple[str, list[tuple[str, int]]]:
    """ローカルプレビューテスト用の累積モック日別データ（合計428件）を生成する。"""
    start_date = "2025-04-01"
    base = datetime(2025, 4, 1)
    # 合計428件になるように日別カウントを構築
    daily_counts = [1] * 80 + [2] * 90 + [3] * 56
    days = [
        ((base + timedelta(days=i)).strftime("%Y-%m-%d"), count)
        for i, count in enumerate(daily_counts)
    ]
    return start_date, days


def main() -> None:
    """累積コントリビューション履歴を取得（またはモック使用）してSVGファイルを生成する。"""
    parser = argparse.ArgumentParser(description="Generate cyberpunk GitHub total contributions SVG.")
    parser.add_argument("--mock", action="store_true", help="Use dummy contribution data for local preview.")
    args = parser.parse_args()

    if args.mock:
        start_date, days = _build_mock_history()
    else:
        token = os.environ.get("GH_TOKEN")
        start_date, days = fetch_contribution_history(USERNAME, token)

    series_info = build_cumulative_series(start_date, days)
    svg_content = build_total_contributions_svg(series_info)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)


if __name__ == "__main__":
    main()
