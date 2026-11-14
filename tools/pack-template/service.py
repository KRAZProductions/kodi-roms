# KRAZ ROM pack: copies this pack's ROMs into SQUID's games folder
# (special://home/<source name>/) and makes sure Kodi has a games source for it.
import json
import os
import shutil
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
HOME = xbmcvfs.translatePath('special://home/')
SOURCES = xbmcvfs.translatePath('special://profile/sources.xml')


def log(msg):
    xbmc.log('[%s] %s' % (ADDON_ID, msg), xbmc.LOGINFO)


def ensure_source(name, path):
    """Add a <games> source to sources.xml. Returns True if it was added."""
    if os.path.exists(SOURCES):
        tree = ET.parse(SOURCES)
        root = tree.getroot()
    else:
        root = ET.Element('sources')
        tree = ET.ElementTree(root)
    games = root.find('games')
    if games is None:
        games = ET.SubElement(root, 'games')
        ET.SubElement(games, 'default', {'pathversion': '1'})
    for src in games.findall('source'):
        if (src.findtext('name') or '') == name:
            return False
    src = ET.SubElement(games, 'source')
    ET.SubElement(src, 'name').text = name
    ET.SubElement(src, 'path', {'pathversion': '1'}).text = path
    ET.SubElement(src, 'allowsharing').text = 'true'
    tmp = SOURCES + '.tmp'
    tree.write(tmp, encoding='utf-8', xml_declaration=False)
    os.replace(tmp, SOURCES)
    return True


def is_art(fn):
    return fn.lower().endswith(('.png', '.jpg', '.jpeg'))


def copy_missing(src_dir, dst_dir):
    copied = 0
    games = 0
    for fn in sorted(os.listdir(src_dir)):
        s = os.path.join(src_dir, fn)
        d = os.path.join(dst_dir, fn)
        if not os.path.isfile(s):
            continue
        if os.path.isfile(d) and os.path.getsize(d) == os.path.getsize(s):
            continue
        tmp = d + '.part'
        shutil.copyfile(s, tmp)
        os.replace(tmp, d)
        copied += 1
        if not is_art(fn):
            games += 1
    return copied, games


def main():
    with open(os.path.join(ADDON_DIR, 'pack.json')) as f:
        pack = json.load(f)
    name = pack['source']
    roms = os.path.join(ADDON_DIR, 'roms')
    total = len([f for f in os.listdir(roms) if not is_art(f)])
    dst = os.path.join(HOME, name)
    try:
        if not os.path.isdir(dst):
            os.makedirs(dst)
        copied, games = copy_missing(roms, dst)
        added = ensure_source(name, 'special://home/%s/' % name)
    except OSError as e:
        # Folder not writable: point a source straight at the pack's own copy.
        log('copy to %s failed (%s), using the add-on folder' % (dst, e))
        name = name + ' (Backup)'
        copied = games = total
        added = ensure_source(name, 'special://home/addons/%s/roms/' % ADDON_ID)
    log('%s: %d files copied, %d of %d games, source added=%s' % (name, copied, games, total, added))
    if copied or added:
        msg = '%s: %d games restored' % (name, games)
        if added:
            msg += ' - restart Kodi to see them'
        xbmcgui.Dialog().notification('KRAZ ROMs', msg, xbmcgui.NOTIFICATION_INFO, 8000)


main()
