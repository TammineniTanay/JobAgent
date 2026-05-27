import requests

repos = [
    ("vanshb03/New-Grad-2026", "dev"),
    ("pittcsc/Summer2025-Internships", "dev"),
]

for repo, branch in repos:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/README.md"
    resp = requests.get(url, timeout=20)
    print(f"\n=== {repo} (HTTP {resp.status_code}) ===")
    if resp.status_code == 200:
        # print first 800 chars to see the table format
        print(resp.text[:800])
    print()
