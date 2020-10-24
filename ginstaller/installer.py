import venv
import os
import sys
import asyncio
import orjson
import aiofiles
import aiohttp
import re
import signal
import functools
import psutil
import pkg_resources
import weakref
from pathlib import Path

from logbook import Logger
from logbook.more import ColorizedStderrHandler

from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QSystemTrayIcon
from PyQt5.QtWidgets import QMenu

from quamash import QEventLoop
from cachetools import TTLCache
from distutils.version import StrictVersion

from ginstaller.asynccache import selfcachedcoromethod
from ginstaller.download import downloadFile
from ginstaller.ui import *


def get_version(package):
    return pkg_resources.get_distribution(package).version


async def shell(arg):
    p = await asyncio.create_subprocess_shell((arg),
                                              stdin=asyncio.subprocess.PIPE,
                                              stdout=asyncio.subprocess.PIPE)

    stdout, stderr = await p.communicate()
    return stdout.decode()

logger = Logger('galacteek')
loggerI = Logger('galacteek.runner')


class ColorizedHandler(ColorizedStderrHandler):
    dark_colors = ["black", "darkred", "darkgreen", "brown", "darkblue",
                   "purple", "teal", "lightgray"]
    light_colors = ["darkgray", "red", "green", "yellow", "blue",
                    "fuchsia", "turquoise", "white"]

    def get_color(self, record):
        return 'darkred'


class GalacteekProcessProtocol(asyncio.SubprocessProtocol):
    def __init__(self, outCallback=None):
        self._output = bytearray()
        self.eventStarted = asyncio.Event()
        self.ioCallback = outCallback
        self.process = None

    def pipe_data_received(self, fd, data):
        try:
            msg = data.decode().strip()
        except BaseException:
            return

        self._output.extend(data)

        for line in msg.split('\n'):
            if self.ioCallback:
                self.ioCallback(line)

            if self.process:
                loggerI.debug(f'G/{self.process.pid}: {line}')
            else:
                loggerI.debug(f'G/unknown: {line}')

    def process_exited(self):
        if self.process:
            loggerI.debug(f'G/{self.process.pid}: purging process')
            del self.process


class GalacteekEnvBuilder(venv.EnvBuilder):
    def post_setup(self, context):
        self.setUp(context)

    def setUp(self, context):
        self.envDir = Path(context.env_dir)
        self.binDir = Path(context.bin_path)
        self.context = context

    def environ2(self):
        env = os.environ.copy()
        venvDir = str(self.envDir)

        libpath = os.path.join(
            venvDir, 'lib',
            'python%d.%d' % sys.version_info[:2],
            'site-packages')

        env['VIRTUAL_ENV'] = venvDir

        env['PATH'] = f'{venvDir}/bin:/bin:/usr/bin:/sbin'
        env['PYTHONPATH'] = libpath
        return env

    def environ(self):
        env = os.environ.copy()
        vinfo = sys.version_info[:2]
        home = os.getenv('HOME')
        env['PATH'] = f'{home}/.local/bin:/bin:/usr/bin:/sbin'
        env['PYTHONPATH'] = \
            '{home}/.local/lib/python{v1}.{v2}/site-packages/'.format(
                home=home,
                v1=vinfo[0],
                v2=vinfo[1]
        )
        logger.debug(f'Environ is: {env}')
        return env

    async def runGalacteek(self, args=[]):
        loop = asyncio.get_event_loop()

        cmd = ['galacteek'] + args

        logger.debug(f'Running galacteek process using command: '
                     f'{cmd}')

        gProtocol = GalacteekProcessProtocol()

        proc = loop.subprocess_exec(
            lambda: gProtocol,
            *cmd,
            env=self.environ(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        transport, proto = await proc
        psProc = psutil.Process(transport.get_pid())
        gProtocol.process = psProc
        return psProc


class PIPProtocol(asyncio.SubprocessProtocol):
    def __init__(self, outCallback):
        self._output = bytearray()
        self.eventStarted = asyncio.Event()
        self.ioCallback = outCallback

    def pipe_data_received(self, fd, data):
        try:
            msg = data.decode().strip()
        except BaseException:
            return

        self._output.extend(data)

        for line in msg.split('\n'):
            if self.ioCallback:
                self.ioCallback(line)

            logger.debug(f'PIP: {line}')

    def process_exited(self):
        pass


async def pipExecOld(loop, venvCtx, args, env=None, callback=None):
    pipProto = PIPProtocol(callback)
    cmd = [str(Path(venvCtx.bin_path).joinpath('pip'))]
    cmd += args

    f = loop.subprocess_shell(
        lambda: pipProto,
        ' '.join(cmd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE

    )

    transport, proto = await f
    return proto._output


class PIPRunner:
    def __init__(self, venv):
        self.venv = venv

    async def pipExec(self, args, env=None, callback=None, systemPip=False):
        cmd = ['pip'] + args
        logger.debug(f'pip exec: {cmd}')

        proc = await asyncio.create_subprocess_shell(
            ' '.join(cmd),
            env=env if env else self.venv.environ(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        while True:
            line = await proc.stdout.readline()
            if line:
                logger.debug(f'pip exec: {cmd}: {line}')
                yield 0, line.decode()
            else:
                break

        await proc.wait()
        if proc.returncode != 0:
            err = await proc.stderr.read()
            logger.debug(f'pip ERR: {err}')
            raise Exception('Pip failed')

    async def pipPackageVersion(self, package, env=None):
        try:
            async for fd, line in self.pipExec(
                    ['show', package]):
                ma = re.search(r'Version:\s([\d\.]+)', line)
                if ma:
                    return StrictVersion(ma.group(1))
        except Exception as e:
            logger.debug(str(e))

    async def pipInstallWheel(self, wheel, env=None):
        try:
            async for fd, line in self.pipExec(
                    ['install', '--user', wheel]):
                yield line
        except Exception as e:
            logger.debug(str(e))

    async def pipInstall(self, pkg, env=None, systemPip=True):
        try:
            async for fd, line in self.pipExec(
                    ['install', '--user', pkg]):
                print(line)
        except Exception as e:
            logger.debug(str(e))


class InstallerApplication(QApplication):
    def __init__(self, args=[]):
        super().__init__(args)

        self.lhandler = ColorizedHandler(level='DEBUG', bubble=True)
        self.lhandler.force_color()
        self.lhandler.push_application()

        logger.debug('Init')

        self._loop = None
        self._venv = None
        self._running = True
        self._gProcesses = weakref.WeakValueDictionary()
        self.cache = TTLCache(8, 120)
        self.lock = asyncio.Lock()

        self.initSystemTray()
        self._venv = self.venvBuilder()
        self._pipRunner = PIPRunner(self.venv)
        self.setupLoop()

        asyncio.ensure_future(self.installerLoop())

    @property
    def loop(self):
        return self._loop

    @property
    def venv(self):
        return self._venv

    @property
    def running(self):
        return self._running

    @property
    def pip(self):
        return self._pipRunner

    def initSystemTray(self):
        self.systemTray = QSystemTrayIcon(self)
        self.systemTray.setIcon(getIcon('ginstaller.png'))
        self.systemTray.show()
        self.systemTray.activated.connect(self.onSystemTrayIconClicked)

        systemTrayMenu = QMenu('Installer')
        systemTrayMenu.addSeparator()

        actionQuit = systemTrayMenu.addAction('Quit')
        actionQuit.triggered.connect(self._exit)

        self.systemTray.setContextMenu(systemTrayMenu)

    def onSystemTrayIconClicked(self, reason):
        if reason == QSystemTrayIcon.Unknown:
            pass
        elif reason == QSystemTrayIcon.Context:
            pass
        elif reason == QSystemTrayIcon.DoubleClick:
            pass
        else:
            pass

    def venvBuilder(self):
        vBuilder = GalacteekEnvBuilder()
        home = os.getenv('HOME')
        self.iPath = Path(f'{home}/.galacteek-installer')
        self.iPath.mkdir(parents=True, exist_ok=True)
        self.venvsPath = self.iPath.joinpath('venvs')
        self.venvsPath.mkdir(parents=True, exist_ok=True)
        self.statusPath = self.iPath.joinpath('install.json')
        self.venvPath = self.venvsPath.joinpath('venvi')

        if not self.venvPath.exists():
            vBuilder.create(str(self.venvPath))
        else:
            context = vBuilder.ensure_directories(str(self.venvPath))
            vBuilder.setUp(context)

        return vBuilder

    async def readStatus(self):
        if not self.statusPath.exists():
            await self.writeStatus({
                'packages': {
                    'galacteek': {
                        'latest_installed_release': None
                    }
                }
            })

        try:
            async with aiofiles.open(str(self.statusPath), 'r+t') as fd:
                data = await fd.read()
                return orjson.loads(data)

            await fd.close()
        except Exception as e:
            logger.debug(str(e))

    async def writeStatus(self, data: dict):
        try:
            async with aiofiles.open(str(self.statusPath), 'w+t') as fd:
                await fd.write(orjson.dumps(data).decode())

            await fd.close()
        except Exception as e:
            logger.debug(str(e))

    def setupLoop(self):
        loop = QEventLoop(self)
        asyncio.set_event_loop(loop)
        self._loop = loop

        self.loop.add_signal_handler(
            signal.SIGINT,
            functools.partial(self.signalHandler, 'SIGINT'),
        )

    def signalHandler(self, sig):
        if sig == 'SIGINT':
            self._exit()

    def _exit(self):
        self._running = False
        self.quit()

    def parseVersion(self, version):
        try:
            v = StrictVersion(version)
            return v if v.version else None
        except Exception:
            pass

    async def instancesCount(self):
        count = 0
        async for proc in self.instances():
            count += 1
        logger.debug(f'Instances count {count}')
        return count

    async def instances(self):
        async with self.lock:
            for pid, p in self._gProcesses.items():
                try:
                    status = p.status()
                    if status and status in ['running', 'sleeping']:
                        logger.debug(f'Instance with pid {p.pid}: {status}')
                        yield p
                except Exception as err:
                    logger.debug(f'COUNT ERR {err}')
                    continue

    async def installerLoop(self):
        while self.running:
            await self.upgrade()

            if await self.instancesCount() == 0:
                await self.startInstance()

            await asyncio.sleep(60)

    async def upgrade(self):
        info = await self.getPkgInfo()
        lRelease = await self.getLatestRelease()

        if 0:
            status = await self.readStatus()
            installed = \
                status['packages']['galacteek']['latest_installed_release']
            vInstalled = self.parseVersion(installed)

        vInstalled = await self.pip.pipPackageVersion('galacteek')

        needUpgrade = (vInstalled is None) or \
            (lRelease and vInstalled and lRelease > vInstalled)

        if needUpgrade:
            if 'releases' not in info:
                return

            release = info['releases'][str(lRelease)]

            for rinfo in release:
                if rinfo.get('packagetype') != 'bdist_wheel':
                    # Only use wheels
                    continue

                dialog = DefaultProgressDialog()
                dialog.show()

                wPath = await self.fetchWheel(rinfo, dialog)

                if wPath and await self.installWheel(rinfo, wPath, dialog):
                    logger.info('Upgrade success')

    async def startInstance(self):
        process = await self.venv.runGalacteek()

        if process:
            logger.info('Started galacteek process')
            self._gProcesses[process.pid] = process
        else:
            logger.info('Failed to run galacteek process')

    async def fetchWheel(self, rinfo, dialog):
        url = rinfo['url']
        wheelPath = None

        try:
            logger.debug(f'Fetching wheel from {url}')

            async for msg in downloadFile(url):
                if msg[0] == 0:
                    st, read, clength = msg
                    progress = (read * 100) / clength
                    dialog.progress(progress)
                elif msg[0] == 1:
                    st, path = msg
                    wheelPath = path
        except Exception as err:
            logger.debug(f'Error fetching wheel {url}: {err}')
        else:
            return wheelPath

    async def installWheel(self, rinfo, wPath, dialog):
        env = os.environ.copy()
        venvDir = str(self.venv.envDir)

        env['VIRTUAL_ENV'] = venvDir

        if 'PYTHONPATH' in env:
            del env['PYTHONPATH']

        env['PATH'] = f'{venvDir}/bin:/bin:/usr/bin:/sbin'

        try:
            async for msg in self.pip.pipInstallWheel(wPath):
                ma = re.search(r'Collecting\s.*', msg)
                if ma:
                    dialog.log(msg)
                ma = re.search('Installing collected packages: (.*)$', msg)
                if ma:
                    dialog.log('Installing galacteek')
                ma = re.search('Successfully installed', msg)
                if ma:
                    dialog.log('Install successfull')
        except Exception as err:
            logger.debug(f'Cannot install wheel: {err}')
            return False
        else:
            return True

    async def getLatestRelease(self):
        data = await self.getPkgInfo()

        if data:
            return self.parseVersion(data['info']['version'])

    @selfcachedcoromethod('cache')
    async def getPkgInfo(self, pkgname='galacteek'):
        url = 'https://pypi.org/pypi/{0}/json'.format(pkgname)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, verify_ssl=False) as resp:
                return await resp.json()


def runinstaller():
    app = InstallerApplication(sys.argv)

    with app.loop:
        app.loop.run_forever()
