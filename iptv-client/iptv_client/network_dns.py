"""Operator DNS lookup bound to the IPTV device; never changes routes or DNS configuration."""
import ipaddress,json,secrets,socket,struct,subprocess,time
from pathlib import Path

def command(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL,timeout=5).strip()

def checksum(data):
    data += b'\0' * (len(data) % 2)
    n = sum(struct.unpack('!%dH' % (len(data)//2), data))
    while n >> 16: n = (n & 65535) + (n >> 16)
    return (~n) & 65535


class MissingIPTVDNS(ConnectionError):pass


def select_dns(st, override=''):
    if override and override.strip():
        return str(ipaddress.IPv4Address(override.strip())), 'manual'
    for values,source in ((st.get('dns-server',[]),'interface'),
                          (st.get('inactive',{}).get('dns-server',[]),'dhcp_inactive')):
        for value in values:
            try:return str(ipaddress.IPv4Address(value)),source
            except ipaddress.AddressValueError:continue
    raise MissingIPTVDNS('No IPTV IPv4 DNS received; configure an IPTV DNS override')


def resolve_entry(name, st, gateway, dns_override=''):
    dev = st['l3_device']; src = st['ipv4-address'][0]['address']
    dns,_ = select_dns(st,dns_override)
    neighbors = json.loads(command('ip', '-j', 'neigh', 'show', gateway, 'dev', dev))
    if not neighbors or not neighbors[0].get('lladdr'):
        subprocess.run(['ping', '-I', dev, '-c', '1', '-W', '1', gateway], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        neighbors = json.loads(command('ip', '-j', 'neigh', 'show', gateway, 'dev', dev))
    peer = neighbors[0]['lladdr']
    mac = Path('/sys/class/net', dev, 'address').read_text().strip()
    tx = secrets.randbelow(65536); sport = secrets.randbelow(10000)+45000
    q = struct.pack('!HHHHHH', tx, 0x100, 1, 0, 0, 0)+b''.join(bytes([len(x)])+x.encode('ascii') for x in name.split('.'))+b'\0\0\1\0\1'
    udp = struct.pack('!HHHH', sport, 53, 8+len(q), 0)+q
    iph = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(udp), tx, 0, 64, 17, 0, socket.inet_aton(src), socket.inet_aton(dns))
    iph = iph[:10]+struct.pack('!H', checksum(iph))+iph[12:]
    pseudo = socket.inet_aton(src)+socket.inet_aton(dns)+struct.pack('!BBH', 0, 17, len(udp))
    udp = udp[:6]+struct.pack('!H', checksum(pseudo+udp) or 65535)+udp[8:]
    frame = bytes.fromhex(peer.replace(':',''))+bytes.fromhex(mac.replace(':',''))+b'\x08\x00'+iph+udp
    def skip(data, i):
        while data[i]:
            if data[i] & 192 == 192: return i+2
            i += data[i]+1
        return i+1
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as s:
        s.bind((dev, 0)); s.settimeout(1)
        for attempt in range(3):
            s.send(frame); end = time.monotonic()+2
            while time.monotonic() < end:
                try: packet = s.recv(65535)
                except socket.timeout: continue
                if len(packet)<42 or packet[12:14]!=b'\x08\x00' or packet[23]!=17: continue
                if packet[26:30]!=socket.inet_aton(dns) or packet[30:34]!=socket.inet_aton(src): continue
                off = 14+(packet[14]&15)*4
                if packet[off:off+4]!=struct.pack('!HH', 53, sport): continue
                data = packet[off+8:]
                if len(data)<12 or data[:2]!=struct.pack('!H', tx) or not data[2]&128: continue
                if data[3]&15: raise ConnectionError('Operator DNS rejected entry lookup')
                qn, an = struct.unpack_from('!HH', data, 4); i=12; answers=[]
                for _ in range(qn): i=skip(data,i)+4
                for _ in range(an):
                    i=skip(data,i); typ, cls, ttl, length=struct.unpack_from('!HHIH',data,i); i+=10
                    if typ==1 and cls==1 and length==4: answers.append(socket.inet_ntoa(data[i:i+4]))
                    i+=length
                if answers: return answers[0]
    raise TimeoutError('Operator DNS entry lookup timed out')

