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
        """Send RTP packets over UDP with fragmentation and FPS control."""
        target_fps = 30
        frame_interval = 1.0 / target_fps

        # FIX: Độ trễ ngắn để client có thời gian khởi tạo socket RTP (khắc phục Connection Error ban đầu)
        time.sleep(0.2)

        while True:
            frameStartFrame = time.time()

            # Dừng gửi nếu request là PAUSE hoặc TEARDOWN
            if self.clientInfo['event'].isSet():
                break

            data = self.clientInfo['videoStream'].nextFrame()

            if data:
                try:
                    address = self.clientInfo['rtspSocket'][1][0]
                    port = int(self.clientInfo['rtpPort'])

                    # Tạo danh sách các gói tin (có thể 1 gói hoặc nhiều gói phân mảnh)
                    packets = self.makeRtpFragmented(data)

                    for i, packet in enumerate(packets):
                        # Gửi gói tin
                        self.clientInfo['rtpSocket'].sendto(packet, (address, port))

                        # Thêm độ trễ nhỏ giữa các fragment để tránh tràn bộ đệm UDP của client
                        if len(packets) > 1 and i < len(packets) - 1:
                            time.sleep(0.0005)

                except:
                    # Lỗi này chủ yếu do socket chưa sẵn sàng hoặc client đóng kết nối.
                    print("Connection Error")

            # FIX: Logic điều chỉnh tốc độ khung hình (FPS)
            time_spent = time.time() - frameStartFrame
            sleep_time = frame_interval - time_spent
            if sleep_time > 0:
                time.sleep(sleep_time)

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

    def makeRtpFragmented(self, payload):
        """Fragment large frames and return a list of RTP packets."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        pt = 26  # MJPEG type
        ssrc = 12345
        MTU_SIZE = 1400


        timestamp = int(time.time() * 1000)
        frameNumber = self.clientInfo['videoStream'].frameNbr()  # Dùng frameNumber để client biết frame nào đang gửi

        # Chia payload thành các chunk
        chunks = []
        for i in range(0, len(payload), MTU_SIZE):
            chunks.append(payload[i:i + MTU_SIZE])

        packets = []

        for i, chunk in enumerate(chunks):
            # Marker = 1 chỉ cho fragment CUỐI CÙNG của khung hình
            marker = 1 if i == len(chunks) - 1 else 0

            rtpPacket = RtpPacket()

            # Số thứ tự (seqnum) tăng cho MỖI gói tin (fragment)
            seqnum = self.sequenceNumber
            self.sequenceNumber = (self.sequenceNumber + 1) % 65536

            # Encode gói tin. Truyền timestamp vào để đảm bảo nhất quán.
            rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, chunk, timestamp)

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