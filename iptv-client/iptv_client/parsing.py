"""Small, non-executing parsers for the observed Huawei IPTV page formats.

JavaScript literals are decoded, never evaluated. A page missing its expected
identity/structure is an error, rather than an empty successful response.
"""
from __future__ import annotations

import csv
import datetime as dt
import html as html_module
from html.parser import HTMLParser
import io
import json
import re
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET


class ParseError(ValueError):
    pass


_STRING = r'''(?:"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*')'''
_STRING_RE = re.compile(_STRING)


def decode_html(data: bytes | str, content_type: str = "") -> str:
    """Prefer valid UTF-8; legacy pages often falsely declare UTF-8 but use GBK."""
    if isinstance(data, str):
        return data
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    declared = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, re.I)
    encodings = ["gb18030"]
    if declared and declared[1].lower() not in ("utf8", "utf-8", "ascii"):
        encodings.insert(0, declared[1])
    for encoding in dict.fromkeys(encodings):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ParseError("Page text is neither valid UTF-8 nor supported legacy encoding")


def js_string(literal: str) -> str:
    """Decode one quoted JS string literal without executing JS expressions."""
    if not _STRING_RE.fullmatch(literal):
        raise ParseError("Expected a JavaScript string literal")
    s, result, i = literal[1:-1], [], 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    while i < len(s):
        if s[i] != "\\":
            result.append(s[i]); i += 1; continue
        i += 1
        if i >= len(s):
            raise ParseError("Truncated string escape")
        c = s[i]; i += 1
        if c in ("u", "x"):
            width = 4 if c == "u" else 2
            value = s[i:i + width]
            if len(value) != width or not re.fullmatch(r"[0-9a-fA-F]+", value):
                raise ParseError("Invalid hexadecimal string escape")
            result.append(chr(int(value, 16))); i += width
        elif c == "\r":
            if i < len(s) and s[i] == "\n": i += 1
        elif c != "\n":
            result.append(escapes.get(c, c))
    value = "".join(result)
    # Join valid UTF-16 surrogate pairs produced by \u escapes; reject lone ones.
    try:
        return value.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError as error:
        raise ParseError("Unpaired Unicode surrogate") from error


class _Forms(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url, self.forms, self.current = base_url, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "form":
            self.current = {"action": urljoin(self.base_url, a.get("action", "")),
                            "method": (a.get("method") or "get").upper(), "fields": {}}
            if a.get("name"): self.current["name"] = a["name"]
            self.forms.append(self.current)
        elif tag.lower() == "input" and self.current is not None and a.get("name"):
            if "disabled" in a: return
            kind = (a.get("type") or "text").lower()
            if kind in ("submit", "button", "reset", "file", "image"): return
            if kind in ("checkbox", "radio") and "checked" not in a: return
            self.current["fields"][a["name"]] = a.get("value") or ""

    def handle_endtag(self, tag):
        if tag.lower() == "form": self.current = None


def parse_forms(page: str, base_url: str = "") -> list[dict]:
    parser = _Forms(base_url)
    parser.feed(page)
    return parser.forms


def _config_records(page: str, kind: str):
    pattern = re.compile(r"CTCSetConfig\s*\(\s*(" + _STRING + r")\s*,\s*(" + _STRING + r")\s*\)")
    for m in pattern.finditer(page):
        if js_string(m[1]) != kind: continue
        record = js_string(m[2])
        fields = {}
        for pair in re.finditer(r"(\w+)\s*=\s*(" + _STRING + r")", record):
            fields[pair[1]] = js_string(pair[2])
        if fields: yield fields


def parse_channels(page: str) -> list[dict]:
    channels, seen = [], set()
    for raw in _config_records(page, "Channel"):
        ident = raw.get("ChannelID", "")
        if not ident or not raw.get("ChannelName"):
            raise ParseError("Channel record missing ID or name")
        if ident in seen: raise ParseError("Duplicate channel ID")
        seen.add(ident)
        channels.append({"id": ident, "name": raw["ChannelName"],
                         "number": raw.get("UserChannelID", ""),
                         "live_url": raw.get("ChannelURL", ""),
                         "timeshift_url": raw.get("TimeShiftURL", ""),
                         "timeshift_enabled": raw.get("TimeShift") == "1",
                         "logo": raw.get("ChannelLogo", raw.get("LogoURL", "")),
                         "raw": raw})
    if not channels: raise ParseError("No channel records found")
    return channels


def parse_services(page: str, base_url: str = "") -> list[dict]:
    services = []
    for raw in _config_records(page, "ServiceEntry"):
        if raw.get("URL"):
            services.append({"name": raw.get("Desc", ""), "url": urljoin(base_url, raw["URL"]),
                             "hotkey": raw.get("HotKey", ""), "raw": raw})
    if not services: raise ParseError("No service entry records found")
    return services


def _assignments(text: str, obj: str) -> dict:
    pattern = re.compile(re.escape(obj) + r"(?:\.(\w+)|\[\s*(" + _STRING + r")\s*\])\s*=\s*(" + _STRING + r"|-?\d+|true|false|null)\s*;")
    fields = {}
    for m in pattern.finditer(text):
        key = m[1] or js_string(m[2])
        value = m[3]
        if value.startswith(("'", '"')): value = js_string(value)
        elif value == "null": value = None
        elif value in ("true", "false"): value = value == "true"
        else: value = int(value)
        fields[key] = value
    return fields


def _timestamp(value: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{14}", value):
        raise ParseError("Invalid programme timestamp shape")
    try: return dt.datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError as error: raise ParseError("Invalid programme timestamp") from error


def parse_epg(page: str, expected_channel: str | None = None) -> dict:
    identity = _assignments(page, "chanCurrentInfoObj")
    ident = str(identity.get("strChanId", ""))
    if not ident: raise ParseError("EPG response missing channel identity")
    if expected_channel is not None and ident != str(expected_channel):
        raise ParseError("EPG response channel identity mismatch")
    if not re.search(r"\bprogCurrentInfo_JS\s*=\s*\[\s*\]", page):
        raise ParseError("EPG response missing programme array")
    programmes = []
    pattern = re.compile(r"\btempObj\s*=\s*\{\s*\}\s*;(.*?)\bprogCurrentInfo_JS\.push\s*\(\s*tempObj\s*\)\s*;", re.S)
    for m in pattern.finditer(page):
        raw = _assignments(m[1], "tempObj")
        # Some portal titles contain unescaped literal quotes, making their JS invalid.
        # Treat this one text field as line data; never evaluate the page.
        if "progName" not in raw:
            title_match = re.search(r'^\s*tempObj\.progName\s*=\s*"([^\r\n]*)";\s*$', m[1], re.M)
            if title_match: raw["progName"] = title_match.group(1)
        if any(k not in raw for k in ("progId", "progName", "startTimeStr", "endTimeStr")):
            raise ParseError("Incomplete EPG programme")
        start, stop = raw["startTimeStr"], raw["endTimeStr"]
        if _timestamp(stop) <= _timestamp(start): raise ParseError("Non-positive programme duration")
        programmes.append({"channel_id": ident, "id": str(raw["progId"]), "title": str(raw["progName"]),
                           "start": start, "stop": stop, "status": str(raw.get("progStatus", "")), "raw": raw})
    if len(re.findall(r"\btempObj\.progId\s*=", page)) != len(programmes):
        raise ParseError("Truncated or unsupported EPG programme structure")
    return {"channel_id": ident, "channel_name": identity.get("chanName", ""),
            "programmes": programmes, "raw": identity}


def parse_logos(page: str, base_url: str = "") -> dict[str, str]:
    """Parse chan objects from hk/zb-channellist pages; only real ID->logo pairs."""
    logos = {}
    chunks = re.split(r"\b(?:var\s+)?chan\s*=\s*\{\s*\}\s*;", page)[1:]
    for chunk in chunks:
        raw = _assignments(chunk, "chan")
        ident, logo = raw.get("channelId"), raw.get("logourl")
        if ident and logo and logo != "null":
            url = urljoin(base_url, str(logo))
            if urlsplit(url).scheme in ("http", "https", ""):
                logos[str(ident)] = url
    # An older data page uses parallel parent arrays.
    ids, urls = {}, {}
    for m in re.finditer(r"parent\.(chanIds|logoUrl)\[(\d+)\]\s*=\s*(" + _STRING + r")\s*;", page):
        (ids if m[1] == "chanIds" else urls)[m[2]] = js_string(m[3])
    for index, ident in ids.items():
        if urls.get(index) and urls[index] != "null":
            url = urljoin(base_url, urls[index])
            if urlsplit(url).scheme in ("http", "https", ""): logos[ident] = url
    return logos


def _single_line(value) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").replace('"', "'")


def export_m3u(channels: list[dict], udpxy_base: str | None = None) -> str:
    lines = ["#EXTM3U"]
    for channel in channels:
        url = channel.get("live_url", "")
        if not url: continue
        if "\n" in url or "\r" in url: raise ParseError("Newline in media URL")
        parsed = urlsplit(url)
        if udpxy_base and parsed.scheme in ("igmp", "udp"):
            url = udpxy_base.rstrip("/") + "/udp/" + parsed.netloc.lstrip("@")
        attrs = [f'tvg-id="{_single_line(channel["id"])}"', f'tvg-name="{_single_line(channel["name"])}"']
        if channel.get("logo"): attrs.append(f'tvg-logo="{_single_line(channel["logo"])}"')
        lines.extend(["#EXTINF:-1 " + " ".join(attrs) + "," + _single_line(channel["name"]), url])
    return "\n".join(lines) + "\n"


def export_csv(channels: list[dict]) -> str:
    out = io.StringIO(newline="")
    fields = ["id", "name", "number", "live_url", "timeshift_enabled", "timeshift_url", "catchup_catalog_member", "logo"]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(channels)
    return out.getvalue()


def export_xmltv(channels: list[dict], programmes: list[dict]) -> str:
    tv = ET.Element("tv", {"generator-info-name": "IPTV independent client"})
    channel_ids = set()
    for channel in sorted(channels,key=lambda c:str(c["id"])):
        ident = str(channel["id"])
        if ident in channel_ids: raise ParseError("Duplicate XMLTV channel ID")
        channel_ids.add(ident)
        node = ET.SubElement(tv, "channel", {"id": ident})
        ET.SubElement(node, "display-name", {"lang": "zh"}).text = channel["name"]
        if channel.get("logo"): ET.SubElement(node, "icon", {"src": channel["logo"]})
    seen = set()
    for programme in sorted(programmes, key=lambda p: (str(p["channel_id"]), p["start"], str(p["id"]))):
        ident = str(programme["channel_id"])
        if ident not in channel_ids: raise ParseError("Programme references unknown channel")
        if _timestamp(programme["stop"]) <= _timestamp(programme["start"]):
            raise ParseError("Non-positive programme duration")
        key = (ident, str(programme["id"]), programme["start"], programme["stop"])
        if key in seen: continue
        seen.add(key)
        node = ET.SubElement(tv, "programme", {"channel": ident, "start": programme["start"] + " +0800", "stop": programme["stop"] + " +0800"})
        ET.SubElement(node, "title", {"lang": "zh"}).text = programme["title"]
    ET.indent(tv)
    return ET.tostring(tv, encoding="unicode", xml_declaration=True) + "\n"
