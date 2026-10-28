import csv
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iptv_client.parsing import *


class ParsingTests(unittest.TestCase):
    def epg(self, title='"新闻"', stop="20261026010000"):
        return '''var progCurrentInfo_JS=[];
          chanCurrentInfoObj.strChanId="42"; chanCurrentInfoObj.chanName="测试";
          tempObj={}; tempObj.progId="p1"; tempObj.progName=''' + title + ''';
          tempObj.startTimeStr="20261026000000"; tempObj.endTimeStr="''' + stop + '''";
          tempObj.progStatus=1; progCurrentInfo_JS.push (tempObj);'''

    def test_gbk_despite_bad_header(self):
        self.assertEqual(decode_html("节目单".encode("gb18030"), "text/html; charset=UTF-8"), "节目单")

    def test_js_literals_not_code(self):
        self.assertEqual(js_string(r'''"a\"b\n\u4e2d\x21"'''), 'a"b\n中!')
        self.assertEqual(js_string(r'''"\ud83d\ude00"'''), "😀")
        with self.assertRaises(ParseError): js_string('"a" + dangerous()')
        with self.assertRaises(ParseError): js_string(r'''"\ud800"''')

    def test_forms_relative_and_entities(self):
        forms = parse_forms('<form action="next.jsp?x=1&amp;y=2" method="post"><input name="x" value="a&amp;b"><input name="empty"><input type="submit" name="buy" value="yes"></form>', 'http://example/EPG/login.jsp')
        self.assertEqual(forms[0]["action"], 'http://example/EPG/next.jsp?x=1&y=2')
        self.assertEqual(forms[0]["fields"], {"x":"a&b", "empty":""})

    def test_channels_keep_raw_and_reject_duplicate(self):
        page = '''Authentication.CTCSetConfig('Channel','ChannelID="42",ChannelName="新闻",UserChannelID="1",ChannelURL="igmp://232.0.0.1:1234",TimeShift="1",TimeShiftURL="rtsp://host/a?accountinfo=x"');'''
        c = parse_channels(page)[0]
        self.assertEqual(c["id"], "42")
        self.assertTrue(c["timeshift_enabled"])
        self.assertEqual(c["raw"]["TimeShiftURL"], "rtsp://host/a?accountinfo=x")
        with self.assertRaises(ParseError): parse_channels(page+page)
        with self.assertRaises(ParseError): parse_channels('<html>SessionTimeOut</html>')

    def test_epg_identity_empty_and_truncated(self):
        data = parse_epg(self.epg(), "42")
        self.assertEqual(data["programmes"][0]["status"], "1")
        with self.assertRaises(ParseError): parse_epg(self.epg(), "43")
        with self.assertRaises(ParseError): parse_epg(self.epg().replace('progCurrentInfo_JS.push (tempObj);',''), "42")
        with self.assertRaises(ParseError): parse_epg(self.epg(stop="20261025010000"), "42")
        empty = 'var progCurrentInfo_JS=[];chanCurrentInfoObj.strChanId="42";'
        self.assertEqual(parse_epg(empty, "42")["programmes"], [])
        with self.assertRaises(ParseError): parse_epg('<html>SessionTimeOut</html>')

    def test_epg_escaped_title(self):
        data=parse_epg(self.epg(r'''"a\"b\n\u4e2d"'''), "42")
        self.assertEqual(data["programmes"][0]["title"], 'a"b\n中')
    def test_portal_unescaped_title(self):
        page=self.epg('"一起"趣"旅行(41)"').replace('tempObj.progName=', '\n tempObj.progName=')
        self.assertEqual(parse_epg(page,'42')['programmes'][0]['title'],'一起"趣"旅行(41)')
        with self.assertRaises(ParseError):parse_epg(page.replace('progCurrentInfo_JS.push (tempObj);',''),'42')

    def test_logos_bound_to_ids(self):
        page='''var chan={};chan["channelId"]="42";chan["logourl"]="../../images/a.jpg";
        var chan={};chan["channelId"]="43";chan["logourl"]="";'''
        self.assertEqual(parse_logos(page, 'http://host/EPG/jsp/default/en/tj_pinterest/hk.jsp'), {"42":"http://host/EPG/jsp/default/images/a.jpg"})

    def test_exports_same_ids_and_xml_escaping(self):
        channels=[{"id":"42","name":"A&B","live_url":"igmp://232.0.0.1:1234","logo":"http://host/a.png?x=1&y=2"}]
        programmes=parse_epg(self.epg('"A&B <新闻>"'), "42")["programmes"]
        text=export_xmltv(channels,programmes+programmes)
        tree=ET.fromstring(text)
        self.assertEqual(len(tree.findall('programme')),1)
        self.assertEqual(tree.find('programme').get('channel'),tree.find('channel').get('id'))
        self.assertEqual(tree.find('programme/title').text,'A&B <新闻>')
        self.assertTrue(tree.find('programme').get('start').endswith(' +0800'))
        m3u=export_m3u(channels,'http://router:4022')
        self.assertIn('tvg-id="42"',m3u)
        self.assertIn('http://router:4022/udp/232.0.0.1:1234',m3u)
        self.assertEqual(next(csv.DictReader(io.StringIO(export_csv(channels))))['id'],'42')
        with self.assertRaises(ParseError): export_xmltv([],programmes)


if __name__ == '__main__': unittest.main()
