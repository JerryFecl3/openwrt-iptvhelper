import secrets
import subprocess

def des_encrypt(key, data, backend='auto'):
    if backend != 'openssl':
        try:
            from Crypto.Cipher import DES
            from Crypto.Util.Padding import pad
            return DES.new(key, DES.MODE_ECB).encrypt(pad(data, 8))
        except ImportError:
            if backend != 'auto': raise
    # E_K(D_K(E_K(x))) == E_K(x). Default OpenSSL provider supports EDE3
    # even where the optional legacy single-DES provider is absent.
    result = subprocess.run(['openssl', 'enc', '-des-ede3', '-K', (key * 3).hex()],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=10)
    if result.returncode: raise RuntimeError('OpenSSL authentication cipher failed')
    return result.stdout

def authenticator(password, challenge, user_id, stb_id, ip, mac, nonce=None):
    if not (len(password)==6 and password.isascii() and password.isdigit()):
        raise ValueError('This adapter supports the verified six-digit password format only')
    if not 1<=len(challenge)<=128:
        raise ValueError('Unexpected challenge length')
    if not stb_id or not stb_id.isascii() or any(ord(c)<33 or ord(c)>126 for c in stb_id):
        raise ValueError('Invalid STB ID characters')
    if not challenge.isascii() or any(ord(c)<33 or ord(c)>126 for c in challenge):
        raise ValueError('Invalid challenge characters')
    values=[nonce or str(secrets.randbelow(90000000)+10000000),challenge,user_id,stb_id,ip,mac,'','CTC']
    if any('$' in v for v in values): raise ValueError('Invalid field separator')
    return des_encrypt(password.encode('ascii').ljust(8,b'0'), '$'.join(values).encode('ascii')).hex().upper()
