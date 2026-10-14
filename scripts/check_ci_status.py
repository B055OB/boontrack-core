import urllib.request
import json
import time
import sys

def check_ci():
    url = "https://api.github.com/repos/B055OB/boontrack-core/actions/runs?per_page=5"
    req = urllib.request.Request(url, headers={"User-Agent": "Python"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            runs = data.get("workflow_runs", [])
            for run in runs:
                print(f"Run #{run['run_number']} ({run['name']}): status={run['status']}, conclusion={run['conclusion']}, branch={run['head_branch']}, sha={run['head_sha'][:7]}")
            return runs
    except Exception as e:
        print(f"API Query error: {e}")
        return []

if __name__ == "__main__":
    check_ci()
