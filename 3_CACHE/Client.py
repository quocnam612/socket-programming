from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, os, time
from collections import deque

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"
TARGET_FRAME_INTERVAL = 1 / 30  # target ~30fps playback
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
        self.startTime = None
        self.cacheName = ""
        self.legacyMode = False
        self.markerSeen = False
        self.markerlessPackets = 0


        self.playedFrames = 0
        self.frameCount = 0
        self.totalFrames = 0
        self.frameBuffer = []
        self.MIN_BUFFER_SIZE = 20
        self.MAX_BUFFER_SIZE = 50 # kích thước tối đa cho buffer


    def createWidgets(self):
        """Build GUI."""
        self.master.grid_rowconfigure(0, weight=1)
        self.master.grid_columnconfigure(0, weight=1)

        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        # Create Play button
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        # Create Pause button
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)

        # Create a scrollable canvas to display the movie
        self.canvas = Canvas(self.master, highlightthickness=0)
        self.canvas.grid(row=0, column=0, columnspan=4, sticky=W + E + N + S, padx=5, pady=5)
        self.vscroll = Scrollbar(self.master, orient=VERTICAL, command=self.canvas.yview)
        self.vscroll.grid(row=0, column=4, sticky=N + S)
        self.hscroll = Scrollbar(self.master, orient=HORIZONTAL, command=self.canvas.xview)
        self.hscroll.grid(row=3, column=0, columnspan=4, sticky=E + W, padx=5)
        self.canvas.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.canvasFrame = Frame(self.canvas)
        self.canvasFrame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.imageWindow = self.canvas.create_window((0, 0), window=self.canvasFrame, anchor="nw")
        self.label = Label(self.canvasFrame)
        self.label.pack()

        self.statsVar = StringVar()
        self.statsVar.set("Frames: 0 | Lost: 0 | Throughput: 0 kbps")
        self.statsLabel = Label(self.master, textvariable=self.statsVar, anchor=W)
        self.statsLabel.grid(row=2, column=0, columnspan=4, sticky=W, padx=5)

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

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            self.frameFragments.clear()
            with self.queueLock:
                self.frameQueue.clear()
                self.packetLoss = 0
                self.legacyMode = False
                self.markerSeen = False
                self.markerlessPackets = 0
            self.bytesReceived = 0
            self.framesDisplayed = 0
            self.lastSeq = 0
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

    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        photo = ImageTk.PhotoImage(Image.open(
            imageFile))  # open the image file and convert it to a PhotoImage object (Tkinter compatible photo image)
        self.label.configure(image=photo)  # update the label with the new image
        self.label.image = photo  # keep a reference to avoid garbage collection (the image disappears)
        self.canvas.itemconfigure(self.imageWindow, width=photo.width(), height=photo.height())
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        currentTime = time.time()
        self.lastFrameTime = currentTime
        self.frameCount += 1

        self.drawProgressBar()

    def drawProgressBar(self):
        W, H = 400, 10

        if not hasattr(self, 'progressCanvas'):
            self.progressCanvas = Canvas(self.master, width=W, height=H,
                                         bg="black", highlightthickness=0)
            self.progressCanvas.grid(row=3, column=0, columnspan=4, pady=5)
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
            # Draw buffer bar starting at the end of the red bar
            self.progressCanvas.create_rectangle(progress_w, 0, progress_w + buffer_w, H,
                                                 fill="gray", outline="gray")

        # --- PROGRESS BAR (đỏ) ---

        if progress_w > 0:
            self.progressCanvas.create_rectangle(0, 0, progress_w, H, fill="red", outline="red")

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
        """Aggregate RTP fragments and push full frames to the playback buffer."""
        currSeqNum = rtpPacket.seqNum()

        # Track packet loss
        if self.lastSeq and currSeqNum > self.lastSeq + 1:
            self.packetLoss += currSeqNum - self.lastSeq - 1
            self.updateStatsLabel()
        if currSeqNum > self.lastSeq:
            self.lastSeq = currSeqNum

        self.bytesReceived += packetSize

        marker = rtpPacket.marker()
        if marker:
            self.markerSeen = True
        elif not self.markerSeen:
            self.markerlessPackets += 1
            if self.markerlessPackets > LEGACY_DETECT_THRESHOLD:
                self.enableLegacyMode()

        # Use timestamp as frame ID (safer than seqNum)
        frameId = rtpPacket.timestamp()
        fragment = self.frameFragments.setdefault(frameId, bytearray())
        fragment.extend(rtpPacket.getPayload())

        # Finalize only when marker bit is set (or legacy mode fallback)
        finalize = marker or self.legacyMode
        if finalize and frameId in self.frameFragments:
            frameData = bytes(self.frameFragments.pop(frameId))

            # Validate JPEG magic bytes before enqueue
            if frameData.startswith(b'\xff\xd8') and frameData.endswith(b'\xff\xd9'):
                self.enqueueFrame(frameId, frameData)
            else:
                print(f"Discarded invalid frame {frameId}, size={len(frameData)}")

        self.updateStatsLabel()

    def enableLegacyMode(self):
        self.legacyMode = True
        self.markerlessPackets = 0
        self.frameFragments.clear()

    def enqueueFrame(self, frameId, frameData):
        with self.queueLock:
            self.frameQueue.append((frameId, frameData))
            while len(self.frameQueue) > 120:
                self.frameQueue.popleft()
        self.bufferEvent.set()

    def playbackLoop(self):
        """Display frames at a steady cadence for smooth playback."""
        nextFrameDeadline = time.time()
        while not self.displayEvent.is_set():
            frame = None
            with self.queueLock:
                if self.frameQueue:
                    frame = self.frameQueue.popleft()

            if frame:
                frameId, frameData = frame
                self.frameNbr = frameId
                self.framesDisplayed += 1
                self.playedFrames += 1
                self.updateMovie(self.writeFrame(frameData))
                self.updateStatsLabel()
                nextFrameDeadline = max(time.time(), nextFrameDeadline)
                sleepTime = max(0, nextFrameDeadline - time.time())
            else:
                self.bufferEvent.wait(TARGET_FRAME_INTERVAL)
                self.bufferEvent.clear()
                sleepTime = TARGET_FRAME_INTERVAL

            time.sleep(sleepTime)
            nextFrameDeadline = time.time() + TARGET_FRAME_INTERVAL


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
        elapsed = max(time.time() - self.startTime, 0.001) if self.startTime else 0.001
        kbps = (self.bytesReceived * 8) / 1000 / elapsed
        text = f"Frames: {self.framesDisplayed} | Lost: {self.packetLoss} | Throughput: {kbps:.1f} kbps"
        self.statsVar.set(text)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:  # When the user presses cancel, resume playing.
            self.playMovie()
