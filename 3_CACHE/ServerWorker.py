import re
import socket
import threading
import time  # Cần thiết cho việc điều chỉnh FPS và độ trễ khởi động
from random import randint

from RtpPacket import RtpPacket
from VideoStream import VideoStream


class ServerWorker:
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'

    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2

    clientInfo = {}

    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        self.sequenceNumber = 0  # Khởi tạo Sequence Number cho các gói RTP
        self.rtp_clock_rate = 90000 # 90 kHz RTP clock
        self. targetFPS = 30
        self. tsPerFrame = int(self.rtp_clock_rate / self.targetFPS)
        self.currentTimeStamp = 0


    def run(self):
        threading.Thread(target=self.recvRtspRequest).start()

    def recvRtspRequest(self):
        """Receive RTSP request from the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        while True:
            data = connSocket.recv(256)
            if data:
                print("Data received:\n" + data.decode("utf-8"))
                self.processRtspRequest(data.decode("utf-8"))

    def processRtspRequest(self, data):
        """Process RTSP request sent from the client."""
        # Get the request type
        request = data.split('\n')
        line1 = request[0].split(' ')
        requestType = line1[0]

        # Get the media file name
        filename = line1[1]

        # Get the RTSP sequence number
        seq = request[1].split(' ')

        # Process SETUP request
        if requestType == self.SETUP:
            if self.state == self.INIT:
                # Update state
                print("processing SETUP\n")

                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    total_frames = self.clientInfo['videoStream'].getTotalFrames()
                    self.clientInfo['totalFrames'] = total_frames
                    print(f"Total frames in video: {total_frames}")
                    self.state = self.READY
                except IOError:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
                    return  # Thoát nếu lỗi file

                # Generate a randomized RTSP session ID
                self.clientInfo['session'] = randint(100000, 999999)

                # Try to extract the client's RTP port from the Transport header
                rtp_port = None
                for ln in request:
                    if 'client_port' in ln or 'client-port' in ln or 'transport' in ln.lower():
                        m = re.search(r'client[_-]?port\s*=\s*(\d+)', ln)
                        if m:
                            rtp_port = m.group(1)
                            break

                if not rtp_port:
                    print('Could not parse client RTP port from SETUP request')
                    self.replyRtsp(self.CON_ERR_500, seq[1])
                    return

                self.clientInfo['rtpPort'] = rtp_port

                # Send RTSP reply
                self.replyRtsp(self.OK_200, seq[1])

        # Process PLAY request
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("processing PLAY\n")
                self.state = self.PLAYING

                # Tạo socket mới cho RTP/UDP
                self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65535)
                self.replyRtsp(self.OK_200, seq[1])

                # Tạo luồng mới và bắt đầu gửi gói RTP
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(target=self.sendRtp)
                self.clientInfo['worker'].start()

        # Process PAUSE request
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                print("processing PAUSE\n")
                self.state = self.READY

                self.clientInfo['event'].set()

                self.replyRtsp(self.OK_200, seq[1])

        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")

            self.clientInfo['event'].set()

            self.replyRtsp(self.OK_200, seq[1])

            # Đóng socket RTP
            try:
                self.clientInfo['rtpSocket'].close()
            except:
                pass

    def sendRtp(self):
        targetfps = self.targetFPS
        frameinterval = 1.0 / targetfps
        nextSendTime = time.time() + 0.2  # small startup delay for client RTP readiness

        # Initialize timestamp at PLAY
        self.currentTimeStamp = 0

        while True:
            if self.clientInfo['event'].isSet():
                break

            # Pacing: wait until next scheduled frame send time
            sleep_time = max(0, nextSendTime - time.time())
            if sleep_time > 0:
                time.sleep(sleep_time)

            data = self.clientInfo['videoStream'].nextFrame()
            if not data:
                # End of stream or read error; you might loop or break
                continue

            address = self.clientInfo['rtspSocket'][1][0]
            port = int(self.clientInfo['rtpPort'])

            # Use the same RTP timestamp for all fragments of this frame
            timestamp = self.currentTimeStamp

            packets = self.makeRtpFragmented(data, timestamp)

            # Send fragments with tiny spacing to avoid UDP buffer bursts
            for i, packet in enumerate(packets):
                try:
                    self.clientInfo['rtpSocket'].sendto(packet, (address, port))
                except Exception as e:
                    print("Connection Error:", e)
                    break
                if i + 1 < len(packets):
                    time.sleep(0.001)  # slightly larger gap to smooth bursts

            # Advance schedule and RTP timestamp
            nextSendTime += frameinterval
            self.currentTimeStamp = (self.currentTimeStamp + self.tsPerFrame) % (1 << 32)

    def makeRtp(self, payload, frameNbr):
        # Phương thức này không còn được sử dụng trực tiếp trong sendRtp ,
        # nhưng được giữ lại vì makeRtpFragmented bao gồm chức năng của nó.
        """RTP-packetize the video data (single packet)."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        marker = 1  # Marker luôn là 1 nếu là 1 gói duy nhất
        pt = 26  # MJPEG type
        seqnum = frameNbr  # Sử dụng frameNbr làm seqnum
        ssrc = 0

        rtpPacket = RtpPacket()
        rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
        return rtpPacket.getPacket()

    def makeRtpFragmented(self, payload, timestamp):
        version, padding, extension, cc = 2, 0, 0, 0
        pt = 26  # MJPEG
        ssrc = 12345
        MTU_SIZE = 1400

        # Fragment payload into MTU-sized chunks
        chunks = [payload[i:i + MTU_SIZE] for i in range(0, len(payload), MTU_SIZE)]
        packets = []

        for i, chunk in enumerate(chunks):
            marker = 1 if i == len(chunks) - 1 else 0

            seqnum = self.sequenceNumber
            self.sequenceNumber = (self.sequenceNumber + 1) % 65536

            rtpPacket = RtpPacket()
            rtpPacket.encode(version, padding, extension, cc,
                             seqnum, marker, pt, ssrc, chunk, timestamp)
            packets.append(rtpPacket.getPacket())

        return packets

    def replyRtsp(self, code, seq):
        """Send RTSP reply to the client."""
        if code == self.OK_200:
            total_frames = self.clientInfo.get('totalFrames', 0)
            reply = (
                    'RTSP/1.0 200 OK\n'
                    'CSeq: ' + seq + '\n'
                                     'Session: ' + str(self.clientInfo['session']) + '\n'
                                                                                     'Total-Frames: ' + str(
                self.clientInfo.get('totalFrames', 0))
            )

            connSocket = self.clientInfo['rtspSocket'][0]
            connSocket.send(reply.encode())

        # Error messages
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")