import os
import requests
import math
from datetime import datetime

# GitHub API設定
TOKEN = os.environ.get("GH_TOKEN")
USERNAME = "Swingray350"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# GraphQLクエリ（直近のコミットデータを取得）
query = """
{
  user(login: "%s") {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
""" % USERNAME

# データ取得
response = requests.post('https://api.github.com/graphql', json={'query': query}, headers=HEADERS)
data = response.json()

# 過去61日分のデータを抽出
days = []
for week in data['data']['user']['contributionsCollection']['contributionCalendar']['weeks']:
    for day in week['contributionDays']:
        days.append(day['contributionCount'])
recent_days = days[-61:] # 直近61日
actual_max = max(recent_days)

# 実際の最大値に基づいて、上限を「一番近い偶数（最低でも8）」に設定
if actual_max <= 8:
    max_count = 8
else:
    max_count = actual_max + 1 if actual_max % 2 != 0 else actual_max

# Y軸の目盛りを計算（0からmax_countまで、均等に4〜5個の目盛りを作る）
# 目盛りのステップ（刻み幅）を偶数になるように計算
step = max(2, math.ceil((max_count / 4) / 2) * 2)
y_tick_values = list(range(0, max_count + 1, step))
if y_tick_values[-1] != max_count:
    y_tick_values.append(max_count)

# SVGの座標（パス）を計算
width, height = 800, 200
points = []

# 軸ラベルを置くために、描画エリアの左と下に少し余白を広げる
for i, count in enumerate(recent_days):
    display_count = count if count > 0 else 0.1
    x = 60 + (i / 60) * 690  # X座標: 60px 〜 750px
    y = 150 - (display_count / max_count * 100) # Y座標: 150px から上に伸びる
    points.append(f"{x},{y}")

path_d = "M " + " L ".join(points)

# Y軸の目盛り生成
y_ticks = ""
for val in y_tick_values:
    y = 150 - (val / max_count * 100)
    y_ticks += f'<line x1="55" y1="{y}" x2="60" y2="{y}" stroke="#7928ca" stroke-width="1"/>\n  '
    y_ticks += f'<text x="50" y="{y + 3}" fill="#7928ca" font-family="monospace" font-size="10" text-anchor="end">{val}</text>\n  '

# X軸の目盛り生成 (-60d 〜 Today まで5日刻み)
x_ticks = ""
for i in range(0, 61, 5):
    x = 60 + (i / 60) * 690
    label = "Today" if i == 60 else f"-{60 - i}d"
    x_ticks += f'<line x1="{x}" y1="150" x2="{x}" y2="155" stroke="#7928ca" stroke-width="1"/>\n  '
    x_ticks += f'<text x="{x}" y="170" fill="#7928ca" font-family="monospace" font-size="10" text-anchor="middle">{label}</text>\n  '

# SVGファイルの生成
svg_content = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <!-- 背景 -->
  <rect width="{width}" height="{height}" fill="#0d0221" rx="10"/>
  
  <!-- テキスト（タイトルと軸ラベル） -->
  <text x="60" y="30" fill="#00f2fe" font-family="monospace" font-size="16" font-weight="bold">Contribution Graph</text>
  <text x="20" y="100" fill="#7928ca" font-family="monospace" font-size="12" transform="rotate(-90 20,100)" text-anchor="middle">Contributions</text>
  <text x="405" y="185" fill="#7928ca" font-family="monospace" font-size="12" text-anchor="middle">Days</text>

  <!-- 軸線・グリッド線 -->
  <line x1="60" y1="150" x2="750" y2="150" stroke="#7928ca" stroke-width="1" opacity="0.8"/> <!-- X軸のベースライン -->
  <line x1="60" y1="50" x2="60" y2="150" stroke="#7928ca" stroke-width="1" opacity="0.8"/>  <!-- Y軸のベースライン -->
  <line x1="60" y1="50" x2="750" y2="50" stroke="#7928ca" stroke-width="1" opacity="0.3" stroke-dasharray="4 4"/> <!-- 上部の点線 -->

  <!-- 縦軸・横軸の目盛りとラベル -->
  {y_ticks}
  {x_ticks}

  <!-- 薄く常に表示される全体波形（ゴースト） -->
  <path d="{path_d}" fill="none" stroke="#00f2fe" stroke-width="2" opacity="0.2"/>

  <!-- 左端から描画され、完成したら消えてループするネオンライン -->
  <path d="{path_d}" fill="none" stroke="#ff007f" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100">
    <animate attributeName="stroke-dashoffset" values="100;0;0" keyTimes="0;0.6;1" dur="1.5s" repeatCount="indefinite" />
  </path>
</svg>
"""

with open("ecg-graph.svg", "w") as f:
    f.write(svg_content)
