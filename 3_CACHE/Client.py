from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk, ImageFile
from PIL import UnidentifiedImageError
import io
import socket, threading, os, time
import math
from collections import deque
from RtpPacket import RtpPacket

ImageFile.LOAD_TRUNCATED_IMAGES = True

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"
TARGET_FRAME_INTERVAL = 1 / 20  # target ~20fps playback
LEGACY_DETECT_THRESHOLD = 2000  # packets without marker before fallback


class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3

    # Initiation..
    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master  # store the master window (tkinter.Tk)
        self.master.protocol("WM_DELETE_WINDOW",
                             self.handler)  # call self.handler when the user closes the window instead of killing the program
        self.createWidgets()  # build the GUI
        self.serverAddr = serveraddr  # IP address of the server
        self.serverPort = int(serverport)  # port number of the server
        self.rtpPort = int(rtpport)  # port number for RTP packets
        self.fileName = filename  # name of the video file
        self.rtspSeq = 0  # Initial RTSP sequence number
        self.sessionId = 0  # Initial RTSP session ID
        self.requestSent = -1  # Last request sent to the server (0 : SETUP, 1 : PLAY, 2 : PAUSE, 3 : TEARDOWN)
        self.teardownAcked = 0  # Flag to indicate if teardown is acknowledged
        self.connectToServer()
        self.frameNbr = 0
        self.prevFrameId = -1
        self.frameBase = None
        self.frameFragments = {}
        self.frameQueue = deque()
        self.queueLock = threading.Lock()
        self.bufferEvent = threading.Event()
        self.displayEvent = threading.Event()
        self.playEvent = threading.Event()
        self.playEvent.set()
        self.playbackThread = None
        self.lastSeq = 0
        self.packetLoss = 0
        self.bytesReceived = 0
        self.framesDisplayed = 0
        self.frameLoss = 0
        self.packetCount = 0
        self.startTime = None
        self.cacheName = ""
        self.legacyMode = False
        self.markerSeen = False
        self.markerlessPackets = 0


        self.playedFrames = 0
        self.frameCount = 0
        self.totalFrames = 0
        self.frameBuffer = []
        self.lastFrame = None
        self.frameTimes = []
        self.displayWidth = 640
        self.displayHeight = 360
        self.frameStep = None
        self.MIN_BUFFER_SIZE = 20
        self.MAX_BUFFER_SIZE = 100 # kích thước tối đa cho buffer


    def createWidgets(self):
        """Build GUI."""
        self.master.grid_rowconfigure(0, weight=1)
        for col in range(4):
            self.master.grid_columnconfigure(col, weight=1)

        self.videoFrame = Frame(self.master, bg="black")
        self.videoFrame.grid(row=0, column=0, columnspan=4, sticky=W + E + N + S, padx=5, pady=5)
        self.videoFrame.bind("<Configure>", self.onWindowResize)
        self.label = Label(self.videoFrame, bg="black")
        self.label.pack(fill=BOTH, expand=True)

        buttonFrame = Frame(self.master)
        buttonFrame.grid(row=1, column=0, columnspan=4, sticky=E + W, padx=2, pady=2)
        for col in range(4):
            buttonFrame.grid_columnconfigure(col, weight=1)

        # Create Setup button
        self.setup = Button(buttonFrame, text="Setup", command=self.setupMovie)
        self.setup.grid(row=0, column=0, padx=5, pady=2, sticky=E + W)

        # Create Play button
        self.start = Button(buttonFrame, text="Play", command=self.playMovie)
        self.start.grid(row=0, column=1, padx=5, pady=2, sticky=E + W)

        # Create Pause button
        self.pause = Button(buttonFrame, text="Pause", command=self.pauseMovie)
        self.pause.grid(row=0, column=2, padx=5, pady=2, sticky=E + W)

        # Create Teardown button
        self.teardown = Button(buttonFrame, text="Teardown", command=self.exitClient)
        self.teardown.grid(row=0, column=3, padx=5, pady=2, sticky=E + W)

        self.statsVar = StringVar()
        self.statsVar.set("Frame: 0 | Packets: 0 | Loss(frames): 0 | FPS: 0.0 | Net: 0 kbps")
        self.statsLabel = Label(self.master, textvariable=self.statsVar, anchor=W)
        self.statsLabel.grid(row=2, column=0, columnspan=4, sticky=E + W, padx=5, pady=(0, 5))


    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)

    def exitClient(self):
        """Teardown button handler."""
        self.stopPlaybackThreads()
        self.sendRtspRequest(self.TEARDOWN)
        self.master.destroy()  # Close the gui window
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)  # Delete the cache image from video
        except FileNotFoundError:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
            self.bufferReady = False

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:

            self.bytesReceived = 0
            self.framesDisplayed = 0
            self.lastSeq = 0
            self.packetCount = 0
            self.frameLoss = 0
            self.prevFrameId = -1
            self.frameBase = None
            self.frameStep = None
            self.frameNbr = 0
            self.frameTimes.clear()
            self.startTime = time.time()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.displayEvent = threading.Event()
            self.displayEvent.clear()
            self.bufferEvent.clear()

            # Create a new thread to listen for RTP packets

            threading.Thread(target=self.listenRtp, daemon=True).start()

            self.playbackThread = threading.Thread(target=self.playbackLoop, daemon=True)
            self.playbackThread.start()
            self.sendRtspRequest(self.PLAY)

    def listenRtp(self):
        """Listen for RTP packets."""
        while True:
            if self.playEvent.isSet():
                break
            try:
                data = self.rtpSocket.recv(65536)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    self.handleRtpPacket(rtpPacket, len(data))

                    # BỎ TOÀN BỘ LOGIC CẬP NHẬT FRAME Ở ĐÂY
                    # Việc cập nhật frame do luồng playbackLoop() đảm nhiệm

            except socket.timeout:
                continue
            except OSError:
                break
        if self.teardownAcked == 1:
            self.closeRtpSocket()
        self.bufferEvent.set()

    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT  # e.g. cache-12345.jpg
        self.cacheName = cachename
        file = open(cachename, "wb")  # open the file in binary write mode
        file.write(data)  # write the received data to the file
        file.close()

        return cachename  # return the file name (e.g. cache-12345.jpg)

    def updateMovie(self, frameData):
        try:
            image = Image.open(io.BytesIO(frameData))
            image.load()  # force full read
        except UnidentifiedImageError:
            print("Skipping invalid frame")
            return

        self.lastFrame = image.copy()
        self.frameTimes.append(time.time())
        self.renderFrame()
        self.lastFrameTime = time.time()
        self.frameCount += 1
        self.drawProgressBar()

    def renderFrame(self):
        if not self.lastFrame:
            return
        self.displayWidth = max(1, self.displayWidth)
        self.displayHeight = max(1, self.displayHeight)
        scale = min(
            self.displayWidth / max(1, self.lastFrame.width),
            self.displayHeight / max(1, self.lastFrame.height),
        )
        if scale <= 0:
            scale = 1
        new_size = (
            max(1, int(self.lastFrame.width * scale)),
            max(1, int(self.lastFrame.height * scale)),
        )
        img = self.lastFrame if new_size == (self.lastFrame.width, self.lastFrame.height) else self.lastFrame.resize(new_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self.label.configure(image=photo)
        self.label.image = photo

    def onWindowResize(self, event):
        self.displayWidth = max(1, event.width)
        self.displayHeight = max(1, event.height)
        self.renderFrame()

    def drawProgressBar(self):
        W, H = 400, 10

        if not hasattr(self, 'progressCanvas'):
            self.progressCanvas = Canvas(self.master, width=W, height=H,
                                         bg="black", highlightthickness=0)
            self.progressCanvas.grid(row=3, column=0, columnspan=4, pady=5)

            # Add a label below the bar for percentages
            self.progressLabel = Label(self.master, text="", anchor="w", font=("Arial", 10, "bold"))
            self.progressLabel.grid(row=4, column=0, columnspan=4, pady=2)

        self.progressCanvas.delete("all")

        # --- PROGRESS BAR (red) ---
        progress_ratio = min(self.playedFrames / self.totalFrames, 1.0) if self.totalFrames > 0 else 0
        progress_w = int(progress_ratio * W)
        if progress_w > 0:
            self.progressCanvas.create_rectangle(0, 0, progress_w, H, fill="red", outline="red")

        # --- BUFFER BAR (gray) ---
        buffer_ratio = len(self.frameBuffer) / self.MAX_BUFFER_SIZE
        buffer_w = int(buffer_ratio * W)
        if buffer_w > 0:
            self.progressCanvas.create_rectangle(progress_w, 0, progress_w + buffer_w, H,
                                                 fill="gray", outline="gray")

        # --- Update percentage label ---
        played_pct = int(progress_ratio * 100)
        buffered_pct = int(buffer_ratio * 100)
        buffered_remain = len(self.frameQueue)
        self.progressLabel.config(
            text=f"Played: {played_pct}% ({self.playedFrames}/{self.totalFrames}) | Buffered: {buffered_pct}% BufferRemain: {buffered_remain}"
        )

    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET,
                                        socket.SOCK_STREAM)  # create a TCP socket (rtspSocket) attribute to connect to the server for RTSP (AF_INET: IPV4, SOCK_STREAM: TCP)
        try:
            self.rtspSocket.connect(
                (self.serverAddr, self.serverPort))  # connect to the server using server address and server port
        except:
            # tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
            tkinter.messagebox.showwarning('Connection Failed',
                                           'Connection to \'%s\' failed.' % self.serverAddr)  # tkMessageBox (Python 2) is changed to tkinter.messagebox (Python 3)

    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""
        # -------------
        # TO COMPLETE
        # -------------

        # Setup request
        # C: SETUP movie.Mjpeg RTSP/1.0
        # C: CSeq: 1
        # C: Transport: RTP/UDP; client_port=25000
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            # Update RTSP sequence number.
            # ...
            self.rtspSeq += 1

            # Write the RTSP request to be sent.
            # request = ...
            request = "SETUP " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(
                self.rtspSeq) + "\nTransport: RTP/UDP; client_port= " + str(self.rtpPort)

            # Keep track of the sent request.
            # self.requestSent = ...
            self.requestSent = self.SETUP

        # Play request
        # C: PLAY movie.Mjpeg RTSP/1.0
        # C: CSeq: 2
        # C: Session: 123456
        elif requestCode == self.PLAY and self.state == self.READY:
            # Update RTSP sequence number.
            # ...
            self.rtspSeq += 1

            # Write the RTSP request to be sent.
            # request = ...
            request = "PLAY " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(
                self.sessionId)

            # Keep track of the sent request.
            # self.requestSent = ...
            self.requestSent = self.PLAY

        # Pause request
        # C: PAUSE movie.Mjpeg RTSP/1.0
        # C: CSeq: 3
        # C: Session: 123456
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            # Update RTSP sequence number.
            # ...
            self.rtspSeq += 1

            # Write the RTSP request to be sent.
            # request = ...
            request = "PAUSE " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(
                self.sessionId)

            # Keep track of the sent request.
            # self.requestSent = ...
            self.requestSent = self.PAUSE

        # Teardown request
        # C: TEARDOWN movie.Mjpeg RTSP/1.0
        # C: CSeq: 5
        # C: Session: 123456
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            # Update RTSP sequence number.
            # ...
            self.rtspSeq += 1

            # Write the RTSP request to be sent.
            # request = ...
            request = "TEARDOWN " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(
                self.sessionId)

            # Keep track of the sent request.
            # self.requestSent = ...
            self.requestSent = self.TEARDOWN
        else:
            return

        # Send the RTSP request using rtspSocket.
        # ...
        self.rtspSocket.send(request.encode())

        print('\nData sent:\n' + request)



    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            reply = self.rtspSocket.recv(1024)  # 1Kb (1024 bytes) is more than enough to receive the RTSP reply

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))  # Decode the reply from bytes to string

            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                self.rtspSocket.shutdown(socket.SHUT_RDWR)
                self.rtspSocket.close()
                break

    # Example of RTSP reply from the server:
    # S: RTSP/1.0 200 OK
    # S: CSeq: 1
    # S: Session: 123456
    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        lines = [ln.strip() for ln in data.strip().splitlines() if ln.strip()]
        seqNum = int(lines[1].split(' ')[1])  # 1 (from the example)

        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            # New RTSP session ID
            if self.sessionId == 0:
                self.sessionId = session

            # Process only if the session ID is the same
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200:  # 200 (from the example)
                    if self.requestSent == self.SETUP:
                        # -------------
                        # TO COMPLETE
                        # -------------
                        # Update RTSP state.
                        # self.state = ...
                        self.state = self.READY

                        # Open RTP port.
                        self.openRtpPort()
                    elif self.requestSent == self.PLAY:
                        # self.state = ...
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        # self.state = ...
                        self.state = self.READY

                        # The play thread exits. A new thread is created on resume.
                        self.playEvent.set()  # stop the thread (set() makes the internal flag true, clear() makes it false which means the thread will run)
                        self.displayEvent.set()
                        self.bufferEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        # self.state = ...
                        self.state = self.INIT

                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1
                        self.stopPlaybackThreads()
                        self.closeRtpSocket()
        for line in lines:
            if line.lower().startswith('total-frames'):
                self.totalFrames = int(line.split()[1])
                print("Total Frames: " + str(self.totalFrames))

    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        # -------------
        # TO COMPLETE
        # -------------
        # Create a new datagram socket to receive RTP packets from the server
        # self.rtpSocket = ...
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # socket(IPV4, UDP), UDP for RTP

        # Set the timeout value of the socket to 0.5sec
        # ...
        self.rtpSocket.settimeout(
            0.5)  # receive function will wait for 0.5 sec to receive data before throwing a timeout exception (this allows the listenRtp function to check periodically if the playEvent is set to stop the thread)

        try:
            # Bind the socket to the address using the RTP port given by the client user
            # ...
            self.rtpSocket.bind(('', self.rtpPort))  # '' means any address (INADDR_ANY)
        except:
            tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' % self.rtpPort)

    def handleRtpPacket(self, rtpPacket, packetSize):
        currSeqNum = rtpPacket.seqNum()
        self.packetCount += 1

        # Track packet loss
        if self.lastSeq and currSeqNum > self.lastSeq + 1:
            self.packetLoss += currSeqNum - self.lastSeq - 1
            self.updateStatsLabel()
        if currSeqNum > self.lastSeq:
            self.lastSeq = currSeqNum

        self.bytesReceived += packetSize

        marker = rtpPacket.marker()
        frameId = rtpPacket.timestamp()

        # Flush previous frame if timestamp changed
        if hasattr(self, "lastTimestamp") and frameId != self.lastTimestamp:
            if self.lastTimestamp in self.frameFragments:
                frameData = bytes(self.frameFragments.pop(self.lastTimestamp))
                self.enqueueFrame(self.lastTimestamp, frameData)
        self.lastTimestamp = frameId

        fragment = self.frameFragments.setdefault(frameId, bytearray())
        fragment.extend(rtpPacket.getPayload())

        # Finalize on marker
        if marker and frameId in self.frameFragments:
            frameData = bytes(self.frameFragments.pop(frameId))
            self.enqueueFrame(frameId, frameData)

        self.updateStatsLabel()

    def enableLegacyMode(self):
        self.legacyMode = True
        self.markerlessPackets = 0
        self.frameFragments.clear()

    def enqueueFrame(self, frameId, frameData):
        # sanity check: skip empty or too-small frames
        if not frameData or len(frameData) < 100:  # adjust threshold
            return
        with self.queueLock:
            self.frameQueue.append((frameId, frameData))
            self.frameBuffer.append(frameId)
            if len(self.frameQueue) > self.MIN_BUFFER_SIZE:
                self.frameQueue.popleft()
            if len(self.frameBuffer) > self.MAX_BUFFER_SIZE:
                self.frameBuffer.pop(0)
        self.bufferEvent.set()

    def playbackLoop(self):
        """Display frames at a steady cadence for smooth playback."""
        nextFrameDeadline = time.time()
        # init tạo pre-buffer giúp video load ổn định hơn
        while (len(self.frameQueue) < self.MIN_BUFFER_SIZE) and not self.displayEvent.isSet():
            self.drawProgressBar()
            time.sleep(0.05)
        while not self.displayEvent.is_set():
            frame = None
            with self.queueLock:
                if self.frameQueue:
                    now = time.time()
                    if now > nextFrameDeadline and len(self.frameQueue) > 1:
                        behind = now - nextFrameDeadline
                        dropCount = min(
                            len(self.frameQueue) - 1,
                            int(behind / TARGET_FRAME_INTERVAL),
                        )
                        for _ in range(dropCount):
                            self.frameQueue.popleft()
                            self.playedFrames += 1
                        nextFrameDeadline += dropCount * TARGET_FRAME_INTERVAL
                    frame = self.frameQueue.popleft()

            if frame:
                frameId, frameData = frame
                normId = self.normalizeFrameId(frameId)
                if self.prevFrameId >= 0 and normId > self.prevFrameId + 1:
                    self.frameLoss += normId - self.prevFrameId - 1
                self.prevFrameId = normId
                self.frameNbr = normId
                self.framesDisplayed += 1
                self.playedFrames += 1
                self.updateMovie(frameData)
                self.updateStatsLabel()
                nextFrameDeadline += TARGET_FRAME_INTERVAL
                sleepTime = max(0, nextFrameDeadline - time.time())
            else:
                self.bufferEvent.wait(TARGET_FRAME_INTERVAL)
                self.bufferEvent.clear()
                sleepTime = TARGET_FRAME_INTERVAL
                nextFrameDeadline = time.time() + TARGET_FRAME_INTERVAL

            time.sleep(sleepTime)


    def stopPlaybackThreads(self):
        self.playEvent.set()
        self.displayEvent.set()
        self.bufferEvent.set()

    def closeRtpSocket(self):
        try:
            self.rtpSocket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.rtpSocket.close()
        except:
            pass

    def updateStatsLabel(self):
        now = time.time()
        elapsed = max(now - self.startTime, 0.001) if self.startTime else 0.001
        while self.frameTimes and now - self.frameTimes[0] > 1.0:
            self.frameTimes.pop(0)
        fps = len(self.frameTimes)
        kbps = (self.bytesReceived * 8) / 1000 / elapsed
        text = f"Frame: {self.frameNbr} | Packets: {self.packetCount} | Loss(frames): {self.frameLoss} | FPS: {fps:.1f} | Net: {kbps:.1f} kbps"
        self.statsVar.set(text)

    def normalizeFrameId(self, frameId):
        if self.frameBase is None:
            self.frameBase = frameId
            return 1
        diff = frameId - self.frameBase
        if diff <= 0:
            return 1
        if self.frameStep is None and diff > 0:
            self.frameStep = diff
        elif self.frameStep:
            self.frameStep = math.gcd(self.frameStep, diff) or self.frameStep
        step = self.frameStep or 1
        return diff // step + 1

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:  # When the user presses cancel, resume playing.
            self.playMovie()
