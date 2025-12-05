from time import time
HEADER_SIZE = 12

def encode(self, version, padding, extension, cc, seqnum, marker, pt, ssrc, payload):
    timestamp = int(time())
    header = bytearray(HEADER_SIZE)

    header[0] = (version & 0x03) << 6 | (padding & 0x01) << 5 | (extension & 0x01) << 4 | (cc & 0x0F)
    header[1] = (marker & 0x01) << 7 | (pt & 0x7F)
    header[2:4] = (seqnum >> 8) & 0xFF, seqnum & 0xFF
    header[4:8] = (timestamp >> 24) & 0xFF, (timestamp >> 16) & 0xFF, (timestamp >> 8) & 0xFF, timestamp & 0xFF
    header[8:12] = (ssrc >> 24) & 0xFF, (ssrc >> 16) & 0xFF, (ssrc >> 8) & 0xFF, ssrc & 0xFF

    self.header = header
    self.payload = payload