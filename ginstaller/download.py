import aiohttp
import aiofiles
import os
import os.path
import tempfile
import asyncio
from urllib.parse import urlparse


async def downloadFile(url, loop=None, sslverify=False):
    parsed = urlparse(url)
    path = parsed.path
    fname = os.path.basename(path)

    tmpDir = tempfile.mkdtemp()
    arPath = os.path.join(tmpDir, fname)

    async with aiofiles.open(arPath, 'w+b') as fd:
        bytesRead = 0

        async with aiohttp.ClientSession() as session:
            async with session.get(url, verify_ssl=sslverify) as resp:
                if resp.status == 404:
                    raise Exception('404')

                headers = resp.headers
                clength = int(headers.get('Content-Length'))

                csize = 524288
                ccount = 0

                while True:
                    data = await resp.content.read(csize)
                    if not data or bytesRead >= clength:
                        break

                    ccount += 1
                    await fd.write(data)
                    bytesRead += len(data)
                    await asyncio.sleep(0)
                    yield 0, bytesRead, clength

                yield 1, arPath
