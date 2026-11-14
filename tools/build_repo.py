#!/usr/bin/env python3
"""Build the Kodi repository (zips/, addons.xml, repository zip, index.html)
from the *-Games folders. Usage: build_repo.py [BASE_URL]"""
import hashlib, json, os, shutil, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
BASE = (sys.argv[1] if len(sys.argv) > 1 else
        'https://raw.githubusercontent.com/KRAZProductions/kodi-roms/main').rstrip('/')
REPO_ID, REPO_VER = 'repository.kraz.roms', '1.0.0'
PACK_VER = '1.0.0'
PACKS = [  # folder, add-on id, games source name used by SQUID, title
    ('Jaguar-Games', 'service.kraz.roms.jaguar', 'Jaguar Games', 'Atari Jaguar'),
    ('Lynx-Games', 'service.kraz.roms.lynx', 'Lynx Games', 'Atari Lynx'),
    ('NGP-Games', 'service.kraz.roms.ngp', 'Neo Geo Pocket Games', 'Neo Geo Pocket'),
    ('Supervision-Games', 'service.kraz.roms.supervision', 'Supervision Games', 'Watara Supervision'),
]

def pack_xml(aid, title, n):
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="{aid}" name="{title} ROMs" version="{PACK_VER}" provider-name="KRAZ Productions">
  <requires><import addon="xbmc.python" version="3.0.0"/></requires>
  <extension point="xbmc.python.script" library="service.py">
    <provides>executable game</provides>
  </extension>
  <extension point="xbmc.service" library="service.py" start="login"/>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">{n} {title} games for SQUID-MBC</summary>
    <description lang="en_GB">Installs {n} {title} ROMs into SQUID's games folder and adds the games source.</description>
    <platform>all</platform>
  </extension>
</addon>
'''

def repo_xml():
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="{REPO_ID}" name="KRAZ ROMs Repository" version="{REPO_VER}" provider-name="KRAZ Productions">
  <extension point="xbmc.addon.repository" name="KRAZ ROMs Repository">
    <dir>
      <info compressed="false">{BASE}/zips/addons.xml</info>
      <checksum>{BASE}/zips/addons.xml.md5</checksum>
      <datadir zip="true">{BASE}/zips/</datadir>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">ROM packs for SQUID-MBC</summary>
    <description lang="en_GB">Jaguar, Lynx, Neo Geo Pocket and Supervision ROM packs.</description>
    <platform>all</platform>
  </extension>
</addon>
'''

def write_zip(path, aid, files):
    """files: list of (arcname-inside-addon, source path or bytes)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for arc, src in files:
            name = f'{aid}/{arc}'
            if isinstance(src, (bytes, str)) and not (isinstance(src, str) and os.path.isfile(src)):
                z.writestr(name, src)
            else:
                z.write(src, name)

zips = os.path.join(ROOT, 'zips')
shutil.rmtree(zips, ignore_errors=True)
entries = []
svc = os.path.join(TOOLS, 'pack-template', 'service.py')
for folder, aid, source, title in PACKS:
    roms = sorted(f for f in os.listdir(os.path.join(ROOT, folder))
                  if os.path.isfile(os.path.join(ROOT, folder, f)))
    xml = pack_xml(aid, title, len(roms))
    files = [('addon.xml', xml), ('service.py', svc),
             ('pack.json', json.dumps({'source': source}))]
    files += [(f'roms/{r}', os.path.join(ROOT, folder, r)) for r in roms]
    write_zip(os.path.join(zips, aid, f'{aid}-{PACK_VER}.zip'), aid, files)
    entries.append(xml)
    print(f'{aid}: {len(roms)} roms')

rxml = repo_xml()
write_zip(os.path.join(zips, REPO_ID, f'{REPO_ID}-{REPO_VER}.zip'), REPO_ID, [('addon.xml', rxml)])
entries.append(rxml)
body = '\n'.join(e.split('?>', 1)[1].strip() for e in entries)
ax = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n{body}\n</addons>\n'
with open(os.path.join(zips, 'addons.xml'), 'w') as f:
    f.write(ax)
with open(os.path.join(zips, 'addons.xml.md5'), 'w') as f:
    f.write(hashlib.md5(ax.encode()).hexdigest())
# Root copy of the repository zip + a plain index Kodi can browse as a file source.
rz = f'{REPO_ID}-{REPO_VER}.zip'
shutil.copy(os.path.join(zips, REPO_ID, rz), os.path.join(ROOT, rz))
with open(os.path.join(ROOT, 'index.html'), 'w') as f:
    f.write(f'<!DOCTYPE html>\n<html><body>\n<a href="{rz}">{rz}</a>\n</body></html>\n')
print('base url:', BASE)
