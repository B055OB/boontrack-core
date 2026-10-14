import urllib.request
import json
import sys

def inspect_run():
    url = "https://api.github.com/repos/B055OB/boontrack-core/actions/runs"
    req = urllib.request.Request(url, headers={"User-Agent": "Python"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        latest_run = data["workflow_runs"][0]
        print(f"Run ID: {latest_run['id']}, HTML URL: {latest_run['html_url']}")
        jobs_url = latest_run["jobs_url"]

    req_jobs = urllib.request.Request(jobs_url, headers={"User-Agent": "Python"})
    with urllib.request.urlopen(req_jobs) as resp:
        jobs_data = json.loads(resp.read().decode())
        for job in jobs_data.get("jobs", []):
            print(f"Job: {job.get('name')}, conclusion={job.get('conclusion')}")
            for step in job.get("steps", []):
                print(f"  Step: {step.get('name')}, status={step.get('status')}, conclusion={step.get('conclusion')}")

if __name__ == "__main__":
    inspect_run()
