"""Auto-heal: ensures Genius Art app installed & running on emulator; called by demo_server on bridge failure."""
import subprocess, time, sys, os

ADB = r'D:/android-sdk/platform-tools/adb.exe'
SERIAL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('HEAL_SERIAL', 'emulator-5570')
APK = r'D:/apk-analysis/genius-art/genius-art.apk'
PKG = 'com.aiart.artgenerator.photoeditor.aiimage'
ACT = PKG + '/.newflow.splash.SplashNewActivity'

def sh(*a, **kw):
    return subprocess.run([ADB, '-s', SERIAL] + list(a), capture_output=True, text=True, **kw)

def ensure():
    # install if missing
    r = sh('shell', 'pm', 'path', PKG)
    if r.returncode != 0 or 'base.apk' not in r.stdout:
        print('[heal] installing...')
        sh('install', '-r', '-t', APK)
        sh('shell', 'pm', 'enable', PKG)
    # enable + proxy + frida
    sh('shell', 'pm', 'enable', PKG)
    sh('shell', 'settings', 'put', 'global', 'http_proxy', '10.0.2.2:10808')
    sh('root')
    r = sh('shell', 'ps', '-A')
    if 'fs16' not in r.stdout:
        sh('shell', 'nohup', '/data/local/tmp/fs16', '-D')
        time.sleep(2)
    # launch if dead
    r = sh('shell', 'pidof', PKG)
    if not r.stdout.strip():
        sh('shell', 'am', 'start', '-n', ACT)
        time.sleep(12)
    r = sh('shell', 'pidof', PKG)
    pid = r.stdout.strip()
    print('[heal] pid =', pid)
    return pid

if __name__ == '__main__':
    ensure()
