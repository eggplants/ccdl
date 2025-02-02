from __future__ import annotations

import asyncio
import base64
import os
import re
from abc import ABCMeta, abstractmethod
from collections.abc import Iterable
from io import BytesIO
from typing import Any

from aiohttp import ClientSession
from PIL import Image
from selenium import webdriver

try:
    import winreg

    def get_windwos_proxy():
        sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            sub_key,
            0,
            winreg.KEY_QUERY_VALUE,
        )
        if winreg.QueryValueEx(key, "ProxyEnable")[0] != 0:
            return winreg.QueryValueEx(key, "ProxyServer")[0]

except Exception:

    def get_windwos_proxy():
        return ""


class RqProxy:
    __proxies: dict[str, str] | None = None

    @classmethod
    def set_proxy(cls, http_proxy: str, https_proxy: str):
        cls.__proxies = {}
        if http_proxy:
            cls.__proxies["http"] = f"http://{http_proxy}"
        if https_proxy:
            cls.__proxies["https"] = f"http://{https_proxy}"

    @classmethod
    def get_proxy(cls) -> dict[str, str] | None:
        return None if cls.__proxies is None else cls.__proxies.copy()


_site_reader = {
    "r.binb.jp": ["binb2", r"r.binb.jp/epm/([\w-]+)/", 1],
    "www.cmoa.jp": ["binb2", r"www.cmoa.jp/bib/speedreader/\?cid=([\w-]+)&u0=(\d)&u1=(\d)", 1],
    "booklive.jp": ["binb", r"booklive.jp/bviewer/s/\?cid=([\w-]*)&", 1],
    "takeshobo.co.jp": ["binb", r"[\w-]+.takeshobo.co.jp/manga/([\w-]+)/_files[\w-]*/([\w-]+)/", 0],
    "www.comic-valkyrie.com": ["binb", r"www.comic-valkyrie.com/samplebook/([\w-]*)/", 0],
    "futabanet.jp": ["binb", r"futabanet.jp/common/dld/zip/([\w-]*)/", 0],
    "comic-polaris.jp": ["binb", r"comic-polaris.jp/ptdata/([\w-]*)/([\w-]*)/", 0],
    "www.shonengahosha.co.jp": ["binb", r"www.shonengahosha.co.jp/([\w-]*)/([\w-]*)/", 0],
    "r-cbs.mangafactory.jp": ["binb", "", 1],
    "comic-meteor.jp": ["binb3", "", 0],
    "comic-action.com": ["comic_action", r"episode/([\w-]*)", 0],
    "comic-days.com": ["comic_action", r"episode/([\w-]*)", 1],
    "comic-gardo.com": ["comic_action", r"episode/([\w-]*)", 1],
    "comic-trail.com": ["comic_action", r"episodes/([\w-]*)", 1],
    "comic-zenon.com": ["comic_action", r"episode/([\w-]*)", 0],
    "comicborder.com": ["comic_action", r"episode/([\w-]*)", 0],
    "comicbushi-web.com": ["comic_action", r"episode/([\w-]*)", 1],
    "ichijin-plus.com": ["comic_action", r"episodes/([\w-]*)", 0],
    "kuragebunch.com": ["comic_action", r"episode/([\w-]*)", 1],
    "magcomi.com": ["comic_action", r"episode/([\w-]*)", 0],
    "pocket.shonenmagazine.com": ["comic_action", r"episode/([\w-]*)", 1],
    "shonenjumpplus.com": ["comic_action", r"(?:episode|magazine)/([\w-]*)", 1],
    "www.sunday-webry.com": ["comic_action", r"episode/([\w-]*)", 1],
    "tonarinoyj.jp": ["comic_action", r"episode/([\w-]*)", 0],
    "to-corona-ex.com": ["comic_action", r"episodes/([\w-]*)", 0],
    "viewer.heros-web.com": ["comic_action", r"episode/([\w-]*)", 0],
    "viewer.comic-earthstar.jp": ["comic_earthstar", r"cid=([\w-]*)"],
    "comic-walker.com": ["comic_walker", r"cid=([\w-]*)"],
    "www.ganganonline.com": ["ganganonline", None],
    # "www.manga-doa.com":                ["manga_doa", None],
    # "www.sukima.me":                    ["sukima", None],
    "urasunday.com": ["urasunday", None],
    "ganma.jp": ["ganma", r"ganma.jp/(?:([\w-]*)/([\w-]*)|([\w-]*))"],
    "yanmaga.jp": ["yanmaga", None],
}


class ComicReader(metaclass=ABCMeta):
    @abstractmethod
    def downloader(self):
        ...


class ComicLinkInfo:
    def __init__(self, url) -> None:
        super().__init__()
        self._url = url
        self.site_name = self._site_name()
        self.reader_name = self._reader_name()
        self.param = self._param()

    @property
    def url(self):
        return self._url

    @url.setter
    def url(self, url):
        self._url = url
        self.site_name = self._site_name()
        self.reader_name = self._reader_name()
        self.param = self._param()

    def _site_name(self):
        match = re.search("//(?:(.*?)/|(.*))", self._url)
        if not match:
            return None
        match = match.groups()
        match = match[0] if match[0] else match[1]
        if "takeshobo.co.jp" in match:
            match = "takeshobo.co.jp"
        return match

    def _reader_name(self):
        return SiteReaderLoader.reader_name(self.site_name)

    def _param(self):
        """return [param_regexp:list, param1, param2,...]."""
        param = _site_reader[self.site_name][1:]  # param: [RegExp, p1, p2, ..., pn]
        if param and type(param) == list and param[0] and type(param[0]) == str:
            search = re.search(param[0], self._url)
            if search:
                param[0] = list(search.groups())
        return param


class SiteReaderLoader:
    global _site_reader
    __reader_reg: dict[str, Any] = {}

    # This method raises mypy error:
    # error: "__new__" must return a class instance (got "Optional[ComicReader]")
    def __new__(cls, linkinfo, driver=None) -> ComicReader | None:  # type: ignore[misc]
        reader = cls.__reader_reg.get(linkinfo.reader_name)
        if reader is None:
            return None
        else:
            return reader(linkinfo, driver)

    @classmethod
    def readers(cls):
        return [_site_reader[x][0] for x in _site_reader]

    @classmethod
    def sites(cls):
        return list(_site_reader)

    @classmethod
    def reader_name(cls, site_name):
        return _site_reader[site_name][0] if site_name in _site_reader else None

    @classmethod
    def get_param(cls, site_name):
        r"""return [RegExp, param1, param2,...]."""
        return _site_reader[site_name][1:]

    @classmethod
    def register(cls, reader_name):
        def decorator(reader_cls):
            cls.__reader_reg[reader_name] = reader_cls
            return reader_cls

        return decorator

    @classmethod
    def reader_cls(cls, reader_name):
        if reader_name in cls.__reader_reg:
            return cls.__reader_reg[reader_name]
        else:
            return None


class ProgressBar:
    """Progress bar for terminal display."""

    def __init__(self, total: int) -> None:
        """Inits ProgressBar with total."""
        super().__init__()
        self._space = 50
        self._total = total
        self._cset = 0

    def reset(self):
        self._cset = 0

    def show(self, current_set: int | None = None):
        self._cset += 1
        current_set = current_set if current_set else self._cset
        a = int((current_set / self._total) * self._space)
        b = self._space - a
        text = "\r|{}{}| {:>3s}% ({:>} of {:>})".format(
            "#" * a,
            " " * b,
            str(int((current_set / self._total) * 100)),
            str(current_set),
            str(self._total),
        )
        print(text, end="")
        if a == self._space:
            print("")


class RqHeaders(dict):
    def __init__(self, mapping=None) -> None:
        mapping = mapping if isinstance(mapping, Iterable) else {}
        super().__init__(mapping)
        self.__setitem__(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.83 Safari/537.36",
        )

    def setitem(self, k, v):
        self.__setitem__(k, v)

    def random_ua(self):
        pass


def draw_image(
    img_source,
    img_target,
    src_x,
    src_y,
    swidth,
    sheight,
    x,
    y,
    width=None,
    height=None,
):
    img_target.paste(
        img_source.crop(
            (src_x, src_y, src_x + swidth, src_y + sheight),
        ),
        (x, y),
    )


def cc_mkdir(fpath, model=0) -> int:
    r""":param model: model = 0, include two subfolders of source and target; model = 1, not include."""
    if model == 1:
        if os.path.exists(fpath):
            print(f'\n當前一話的文件夾 "{fpath}" 存在,繼續運行數據將被覆蓋!')
            print("是否繼續運行?(y/n)")
            yn = input()
            return 0 if yn == "y" or yn == "yes" or yn == "Y" else -1
        else:
            if not os.path.exists(fpath):
                os.makedirs(fpath)
            print("創建文件夾: " + fpath)
            return 0
    if os.path.exists(fpath + "/source") and os.path.exists(fpath + "/target"):
        print(f'\n當前一話的文件夾 "{fpath}" 存在,繼續運行數據將被覆蓋,')
        print("是否繼續運行?(y/n)")
        yn = input()
        return 0 if yn == "y" or yn == "yes" or yn == "Y" else -1
    else:
        if not os.path.exists(fpath + "/source"):
            os.makedirs(fpath + "/source")
        if not os.path.exists(fpath + "/target"):
            os.makedirs(fpath + "/target")

        print("創建文件夾: " + fpath)
        return 0


def get_blob_content(driver: webdriver.Chrome, uri):
    """获取浏览器中的blob对象的数据."""
    result = driver.execute_async_script(
        """
        var uri = arguments[0];
        var callback = arguments[1];
        var toBase64 = function(buffer){
            for(
                var r,n=new Uint8Array(buffer),
                t=n.length,
                a=new Uint8Array(4*Math.ceil(t/3)),
                i=new Uint8Array(64),
                o=0,c=0;64>c;++c
            ) i[c]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".charCodeAt(c);
            for(
                c=0;t-t%3>c;c+=3,o+=4
            ) r=n[c]<<16|n[c+1]<<8|n[c+2],a[o]=i[r>>18],a[o+1]=i[r>>12&63],a[o+2]=i[r>>6&63],a[o+3]=i[63&r];
            return t%3===1
            ? (r=n[t-1],a[o]=i[r>>2],a[o+1]=i[r<<4&63],a[o+2]=61,a[o+3]=61)
            : t%3===2&&(
                r=(n[t-2]<<8)+n[t-1],a[o]=i[r>>10],a[o+1]=i[r>>4&63],a[o+2]=i[r<<2&63],a[o+3]=61
            ),new TextDecoder("ascii").decode(a)
        };
        var xhr = new XMLHttpRequest();
        xhr.responseType = 'arraybuffer';
        xhr.onload = function(){ callback(toBase64(xhr.response)) };
        xhr.onerror = function(){ callback(xhr.status) };
        xhr.open('GET', uri);
        xhr.send();
        """,
        uri,
    )
    if type(result) == int:
        raise Exception("Request failed with status %s" % result)
    return base64.b64decode(result)


def win_char_replace(s: str):
    table = str.maketrans(r"|*<>\/:?", "_______?", " ")
    return s.translate(table)


def url_join(*args):
    args = list(args)
    l = len(args)
    for i in range(l):
        args[i] = args[i][1:] if args[i][0] == "/" else args[i]
        args[i] = args[i] + "/" if args[i][-1] != "/" and i != l - 1 else args[i]
    return "".join(args)


def downld_url(url: list, headers=None, cookies=None, bar=None):
    """:param url: url list
    :param headers:  (list, tuple) for each || dict for all
    :param cookies:  (list, tuple) for each || dict for all
    :param bar: ProgressBar object
    :returns: [bstr if success else None, ...]
    """

    async def _dld(index, url, *, max_retries=3, headers=None, cookies=None):
        nonlocal bar
        async with ClientSession(headers=headers, cookies=cookies) as session:
            for _t in range(max_retries):
                async with session.get(url=url) as response:
                    try:
                        r = (index, await response.content.read())
                        break
                    except Exception as e:
                        print(e)
                        r = (index, None)
            bar.show() if bar else None
            return r

    fs = []
    for x in range(len(url)):
        fs.append(
            asyncio.ensure_future(
                _dld(
                    x,
                    url[x],
                    headers=headers[x] if isinstance(headers, (list, tuple)) else headers,
                    cookies=cookies[x] if isinstance(cookies, (list, tuple)) else cookies,
                ),
            ),
        )

    loop = asyncio.get_event_loop()
    done, pedding = loop.run_until_complete(asyncio.wait(fs))

    r_dict = {}
    for d in done:
        r_t = d.result()
        if isinstance(r_t, tuple):
            r_dict[r_t[0]] = r_t[1]
    result = []
    for i in range(len(url)):
        result.append(r_dict.get(i))
    return result


def write2file(
    file_path: str,
    img,
    page_num,
    file_ext: str,
    file_ext_dst: str | None = None,
    bar: ProgressBar | None = None,
):
    """:param img: bytes or []bytes
    :param page_num: total page if isinstance(img, list)t else current
    :param file_ext: jpg | png | webp ...
    """
    if isinstance(img, bytes):
        p = os.path.join(file_path, str(page_num) + "." + file_ext)
        with open(p, "wb") as fp:
            fp.write(img)
        return 0
    elif isinstance(img, list):
        pnum = 1
        for img_ in img:
            p = os.path.join(file_path, str(pnum) + ".")
            if file_ext_dst:
                Image.open(BytesIO(img_)).save(p + file_ext_dst)
            else:
                with open(p + file_ext, "wb") as fp:
                    fp.write(img_)
            if bar is not None:
                bar.show(pnum)
            pnum += 1
        return 0
    else:
        return -1
