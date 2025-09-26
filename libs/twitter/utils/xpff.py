from binascii import hexlify, unhexlify
from hashlib import sha256
from json import dumps
from time import time

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


class XPFFHeaderGenerator:
    def __init__(self, user_agent: str):
        self.base_key = "0e6be1f1e21ffc33590b888fd4dc81b19713e570e805d4e5df80a493c9571a05"
        self.user_agent = user_agent

        self.last_ts = 0
        self.last_guest_id = None
        self.last_xpff = None

    def generate_xpff(self, guest_id: str) -> str:
        current_ts = int(time() * 1e3)
        if (
            self.last_guest_id == guest_id and self.last_xpff and (current_ts - self.last_ts) / 1e3 / 60 < 5  # previous xpff < 5 mins
        ):
            return self.last_xpff

        self.last_ts = int(time() * 1e3)
        self.last_guest_id = guest_id

        fingerprint = {
            "webgl_fingerprint": "",
            "canvas_fingerprint": "",
            "navigator_properties": {"hasBeenActive": "true", "userAgent": self.user_agent, "webdriver": "false"},
            "codec_fingerprint": "",
            "audio_fingerprint": "",
            "audio_properties": None,
            "created_at": self.last_ts,
        }
        fingerprint_str = dumps(fingerprint, separators=(",", ":"))

        key = self._derive_xpff_key(guest_id)
        nonce = get_random_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(fingerprint_str.encode())
        self.last_xpff = hexlify(nonce + ciphertext + tag).decode()
        return self.last_xpff

    def decode_xpff(self, hex_string: str, guest_id: str) -> str:
        key = self._derive_xpff_key(guest_id)
        raw = unhexlify(hex_string)
        nonce = raw[:12]
        ciphertext = raw[12:-16]
        tag = raw[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode()

    def _derive_xpff_key(self, guest_id: str) -> bytes:
        combined = self.base_key + guest_id
        return sha256(combined.encode()).digest()
