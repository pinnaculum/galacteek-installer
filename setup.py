import os
import os.path
import re
import sys
import codecs
import subprocess

from setuptools import setup
from setuptools import Command
from distutils.command.build import build

PY_VER = sys.version_info

if PY_VER >= (3, 6):
    pass
else:
    print('You need python3.6 or newer')
    print('Your python version is {0}'.format(PY_VER))
    raise RuntimeError('Invalid python version')

with codecs.open(os.path.join(os.path.abspath(os.path.dirname(
        __file__)), 'ginstaller', '__init__.py'), 'r', 'latin1') as fp:
    try:
        version = re.findall(r"^__version__ = '([^']+)'\r?$",
                             fp.read(), re.M)[0]
    except IndexError:
        raise RuntimeError('Unable to determine version.')


def run(*args):
    p = subprocess.Popen(*args, stdout=subprocess.PIPE)
    stdout, err = p.communicate()
    return stdout

class build_ui(Command):
    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        run(['pyrcc5', os.path.join('ginstaller', 'ginstaller.qrc'), '-o',
             os.path.join('ginstaller', 'ginstaller_rc.py')])

class _build(build):
    sub_commands = [('build_ui', None)] + build.sub_commands



with open('README.rst', 'r') as fh:
    long_description = fh.read()

deps_links = []
install_reqs = []
with open('requirements.txt') as f:
    lines = f.read().splitlines()
    for line in lines:
        if line.startswith('-e'):
            link = line.split().pop()
            deps_links.append(link)
        else:
            install_reqs.append(line)

setup(
    name='galacteek-installer',
    version=version,
    license='GPL3',
    url='https://github.com/pinnaculum/galacteek-installer',
    description='Galacteek installer',
    long_description=long_description,
    include_package_data=True,
    packages=[
        'ginstaller',
    ],
    install_requires=install_reqs,
    cmdclass={
        'build': _build,
        'build_ui': build_ui
    },
    entry_points={
        'gui_scripts': [
            'ginstaller = ginstaller.installer:runinstaller'
        ]
    },
    classifiers=[
        'Environment :: X11 Applications :: Qt',
        'Framework :: AsyncIO',
        'Topic :: Desktop Environment :: File Managers',
        'Topic :: Internet :: WWW/HTTP :: Browsers',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Topic :: System :: Filesystems',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7'
    ],
    keywords=[
        'asyncio',
        'aiohttp',
        'ipfs'
    ]
)
