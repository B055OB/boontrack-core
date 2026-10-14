import subprocess
import urllib.request
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

def get_token():
    p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, _ = p.communicate('protocol=https\nhost=github.com\n\n')
    for line in out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    return None

class NoAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req:
            # Remove Authorization header when redirected to external host (e.g. Azure blob storage)
            new_req.headers = {k: v for k, v in new_req.headers.items() if k.lower() != 'authorization'}
        return new_req

def fetch_log(job_id: str):
    token = get_token()
    opener = urllib.request.build_opener(NoAuthRedirectHandler())
    url = f"https://api.github.com/repos/B055OB/boontrack-core/actions/jobs/{job_id}/logs"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Python"})
    with opener.open(req) as resp:
        content = resp.read().decode('utf-8', errors='ignore')
        return content

if __name__ == "__main__":
    job_id = sys.argv[1] if len(sys.argv) > 1 else "115989368010"
    log = fetch_log(job_id)
    for line in log.splitlines()[-150:]:
        print(line)
