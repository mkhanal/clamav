#!/usr/bin/env python3
"""Time clamdscan and measure clamd's extra memory, inside a container that has the build under test.

  bench-clamd.py <file>...        (run by run-bench.sh; databases in /db)

Starts clamd with DisableCache yes, scans each file once to warm up, then RUNS (default 7) times, and prints one JSON
line per file: median, min and max wall time in seconds, the clamd CPU time, and the most anonymous and resident
memory clamd added during a scan (sampled every 10 ms), beside the idle size after the databases loaded.
"""
import os, subprocess, sys, time, threading, statistics, json, glob
RUNS = int(os.environ.get('RUNS', '7'))
files = sys.argv[1:]
conf = '/tmp/clamd.conf'
open(conf, 'w').write("""LocalSocket /tmp/clamd.sock
DatabaseDirectory /db
TemporaryDirectory /tmp/scan
User clamav
Foreground yes
LogFile /tmp/clamd.log
MaxThreads 4
DisableCache yes
""")
os.makedirs('/tmp/scan', exist_ok=True)
subprocess.run('useradd -r clamav; chown -R clamav /tmp/scan; touch /tmp/clamd.log; chown clamav /tmp/clamd.log; chmod 644 /tmp/clamd.conf', shell=True, stderr=subprocess.DEVNULL)
env = dict(os.environ, PATH='/opt/clamav/sbin:/opt/clamav/bin:' + os.environ['PATH'])
t0 = time.time()
p = subprocess.Popen(['clamd', '-c', conf], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not os.path.exists('/tmp/clamd.sock'):
    time.sleep(0.2)
time.sleep(1)
print('clamd ready after %.1fs' % (time.time() - t0), flush=True)
def status(pid):
    d = {}
    for l in open('/proc/%d/status' % pid):
        k, _, v = l.partition(':')
        if k in ('VmRSS', 'RssAnon', 'RssFile', 'VmHWM'):
            d[k] = int(v.split()[0]) / 1024
    return d
pid = p.pid
def cpuj(pid):
    f = open('/proc/%d/stat' % pid).read().split(')')[1].split()
    return (int(f[11]) + int(f[12])) / os.sysconf('SC_CLK_TCK')
print('idle', status(pid), flush=True)
res = {}
for f in files:
    def one():
        stop = [False]; st = status(pid); peak = {'RssAnon': st['RssAnon'], 'VmRSS': st['VmRSS']}
        def samp():
            while not stop[0]:
                try:
                    s = status(pid)
                    for k in peak: peak[k] = max(peak[k], s[k])
                except Exception: pass
                time.sleep(0.01)
        th = threading.Thread(target=samp); th.start()
        c0 = cpuj(pid); t = time.time()
        r = subprocess.run(['clamdscan', '-c', conf, '--no-summary', f], env=env, capture_output=True, text=True)
        el = time.time() - t; c1 = cpuj(pid)
        stop[0] = True; th.join()
        return el, c1 - c0, dict(RssAnon=peak['RssAnon']-st['RssAnon'], VmRSS=peak['VmRSS']-st['VmRSS']), r.stdout.strip().replace('\n', ' ')
    one()
    rs = [one() for _ in range(RUNS)]
    ts = sorted(r[0] for r in rs)
    out = dict(file=os.path.basename(f), times=[round(t, 3) for t in ts], verdict=rs[0][3].replace(f + ': ', ''), median=statistics.median(ts), min=ts[0], max=ts[-1],
               cpu_median=statistics.median(r[1] for r in rs), extra_anon_mib=max(r[2]['RssAnon'] for r in rs), extra_rss_mib=max(r[2]['VmRSS'] for r in rs))
    print(json.dumps(out), flush=True)
p.terminate()
