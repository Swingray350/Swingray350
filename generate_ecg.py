import os
import requests
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

# 過去60日分のデータを抽出
days = []
for week in data['data']['user']['contributionsCollection']['contributionCalendar']['weeks']:
    for day in week['contributionDays']:
        days.append(day['contributionCount'])
recent_days = days[-60:] # 直近60日

# SVGの座標（パス）を計算
width, height = 800, 200
max_count = max(recent_days) if max(recent_days) > 0 else 1
points = []

for i, count in enumerate(recent_days):
    x = 50 + (i / 59) * 700  # 左右の余白50px
    y = 150 - (count / max_count * 100) # 下余白50pxから上に伸びる
    points.append(f"{x},{y}")

path_d = "M " + " L ".join(points)

# SVGファイルの生成（薄い背景ライン ＋ アニメーションする光のパルス）
svg_content = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <!-- 背景 -->
  <rect width="{width}" height="{height}" fill="#0d0221" rx="10"/>
  
  <!-- グリッド線（サイバー感の演出） -->
  <line x1="50" y1="150" x2="750" y2="150" stroke="#7928ca" stroke-width="1" opacity="0.5" stroke-dasharray="4 4"/>
  <line x1="50" y1="50" x2="750" y2="50" stroke="#7928ca" stroke-width="1" opacity="0.3" stroke-dasharray="4 4"/>

  <!-- 薄く常に表示される全体波形（ゴースト） -->
  <path d="{path_d}" fill="none" stroke="#00f2fe" stroke-width="2" opacity="0.2"/>

  <!-- 左から右へ走るネオンパルス（ECGエフェクト） -->
  <path d="{path_d}" fill="none" stroke="#ff007f" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="150 2000" stroke-dashoffset="2000">
    <animate attributeName="stroke-dashoffset" from="2000" to="-150" dur="4s" repeatCount="indefinite" />
  </path>
</svg>
"""

with open("ecg-graph.svg", "w") as f:
    f.write(svg_content)
