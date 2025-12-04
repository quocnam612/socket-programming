import os
import socket
import threading
from tkinter import *
import tkinter.messagebox

from PIL import Image, ImageTk

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

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
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer()
        self.frameNbr = 0
        # FPS tracking
        self.lastFrameTime = 0
        self.frameCount = 0
        self.currentFps = 0.0

        #
        self.totalFrames = 0
        self.frameBuffer = []
        self.MAX_BUFFER_SIZE = 30 #kích thước tối đa của buffer

    def createWidgets(self):
        """Build GUI."""
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)

        self.label = Label(self.master, height=19, bg='black')
        self.label.grid(row=0, column=0, columnspan=4,
                        sticky=W+E+N+S, padx=5, pady=5)

        self.fpsLabel = Label(self.master, text="FPS: 0.0", font=("Arial", 12, "bold"), 
                               fg="white", bg="black")
        self.fpsLabel.grid(row=2, column=0, columnspan=4, sticky=W+E, padx=5, pady=2)

    def setupMovie(self):
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)

    def exitClient(self):
        self.sendRtspRequest(self.TEARDOWN)
        self.master.destroy()
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except:
            pass

    def pauseMovie(self):
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)

    def playMovie(self):
        if self.state == self.READY:
            # create the play event before starting the RTP listener thread
            # so the listener can safely check it on timeout/exception.
            self.playEvent = threading.Event()
            self.playEvent.clear()
            threading.Thread(target=self.listenRtp, daemon=True).start()
            self.sendRtspRequest(self.PLAY)

    def listenRtp(self):
        while True:
            try:
                data = self.rtpSocket.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)

                    currFrameNbr = rtpPacket.seqNum()
                    #print("Current Seq Num: " + str(currFrameNbr))

                    if currFrameNbr > self.frameNbr:
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(rtpPacket.getPayload()))

                        frameData = rtpPacket.getPayload()

                        # Buffer frame
                        if len(getattr(self, 'frameBuffer', [])) < self.MAX_BUFFER_SIZE:
                            self.frameBuffer.append(frameData)

                        self.frameCount += 1
                        self.updateMovie(self.writeFrame(frameData))
                        
                        #xóa frame ở buffer sau khi hiển thị
                        if self.frameBuffer:
                            self.frameBuffer.pop(0)
            except:
                # On socket timeout or other exception, check control flags.
                # Use getattr so missing attributes don't raise new exceptions.
                if getattr(self, 'playEvent', None) and getattr(self.playEvent, 'is_set', None):
                    try:
                        if self.playEvent.is_set():
                            break
                    except:
                        pass
                if getattr(self, 'teardownAcked', 0) == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except:
                        pass
                    break

    def writeFrame(self, data):
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        file = open(cachename, "wb")
        file.write(data)
        file.close()
        return cachename

    def updateMovie(self, imageFile):
        # Calculate FPS
        import time
        currentTime = time.time()
        if self.lastFrameTime > 0:
            # Calculate instantaneous FPS for this frame
            timeDelta = currentTime - self.lastFrameTime
            if timeDelta > 0:
                instantFps = 1.0 / timeDelta
                # Use a simple moving average (smooth the FPS display)
                self.currentFps = 0.7 * self.currentFps + 0.3 * instantFps
        self.lastFrameTime = currentTime
        self.frameCount += 1
        
        # Load and display image
        img = Image.open(imageFile)
        photo = ImageTk.PhotoImage(img)
        
        # Update label with image
        self.label.configure(image=photo, height=288)
        self.label.image = photo
        # Update FPS label and window title
        self.fpsLabel.configure(text=f"FPS: {self.currentFps:.1f}")
        self.master.title(f"RTSP Client - FPS: {self.currentFps:.1f}")

        # Vẽ progress bar
        self.drawProgressBar()
        

        #hàm vẽ thanh tiến trìnhh
    def drawProgressBar(self):
        W, H = 400, 10
        
        if not hasattr(self, 'progressCanvas'):
            self.progressCanvas = Canvas(self.master, width=W, height=H,
                                     bg="black", highlightthickness=0)
            self.progressCanvas.grid(row=3, column=0, columnspan=4, pady=5)
        self.progressCanvas.delete("all")

        # --- BUFFER BAR (xám) ---

        progress_ratio = min(self.frameNbr / self.totalFrames, 1.0) if self.totalFrames > 0 else 0
        progress_w = int(progress_ratio * W)

        buffer_w = int((len(self.frameBuffer) / self.MAX_BUFFER_SIZE) * W) + progress_w
        buffer_w = min(max(buffer_w, 0), W)
        
        if buffer_w > 0:
            self.progressCanvas.create_rectangle(0, 0, buffer_w, H, fill="gray", outline="gray")

        # --- PROGRESS BAR (đỏ) ---
        
        if progress_w > 0:
            self.progressCanvas.create_rectangle(0, 0, progress_w, H, fill="red", outline="red")


    def connectToServer(self):
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            # Show the actual exception message to help debugging
            import traceback
            err = traceback.format_exc()
            tkinter.messagebox.showwarning(
                'Connection Failed',
                f"Cannot connect to server {self.serverAddr}:{self.serverPort}\n\n{err}"
            )
            # Mark socket as unusable so other methods can guard against it
            try:
                self.rtspSocket.close()
            except:
                pass
            self.rtspSocket = None

    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""

        # SETUP
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1
            request = f"SETUP {self.fileName} RTSP/1.0\n" \
                      f"CSeq: {self.rtspSeq}\n" \
                      f"Transport: RTP/UDP; client_port={self.rtpPort}\n\n"
            self.requestSent = self.SETUP

        # PLAY
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = f"PLAY {self.fileName} RTSP/1.0\n" \
                      f"CSeq: {self.rtspSeq}\n" \
                      f"Session: {self.sessionId}\n\n"
            self.requestSent = self.PLAY

        # PAUSE
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = f"PAUSE {self.fileName} RTSP/1.0\n" \
                      f"CSeq: {self.rtspSeq}\n" \
                      f"Session: {self.sessionId}\n\n"
            self.requestSent = self.PAUSE

        # TEARDOWN
        elif requestCode == self.TEARDOWN and self.state != self.INIT:
            self.rtspSeq += 1
            request = f"TEARDOWN {self.fileName} RTSP/1.0\n" \
                      f"CSeq: {self.rtspSeq}\n" \
                      f"Session: {self.sessionId}\n\n"
            self.requestSent = self.TEARDOWN

        else:
            return

        self.rtspSocket.send(request.encode())
        print("\nData sent:\n" + request)

    def recvRtspReply(self):
        while True:
            reply = self.rtspSocket.recv(1024)

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))

            if self.requestSent == self.TEARDOWN:
                try:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                except:
                    pass
                break

    def parseRtspReply(self, data):
        # Normalize newlines and split into non-empty lines
        lines = [ln.strip() for ln in data.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return

        try:
            seqNum = int(lines[1].split()[1])
        except Exception:
            return

        if seqNum != self.rtspSeq:
            return

        try:
            session = int(lines[2].split()[1]) if len(lines) > 2 else self.sessionId
        except Exception:
            session = self.sessionId

        if self.sessionId == 0:
            self.sessionId = session

        if self.sessionId != session:
            return

        try:
            code = int(lines[0].split()[1])
        except Exception:
            return


        if code != 200:
            return

        for line in lines:
            if line.lower().startswith("total-frames"):
                try:
                    self.totalFrames = int(line.split(":")[1].strip())
                    print(f"Total frames received from server: {self.totalFrames}")
                except:
                    self.totalFrames = 0                    

        if self.requestSent == self.SETUP:
            self.state = self.READY
            self.openRtpPort()

        elif self.requestSent == self.PLAY:
            self.state = self.PLAYING

        elif self.requestSent == self.PAUSE:
            self.state = self.READY
            if getattr(self, 'playEvent', None):
                try:
                    self.playEvent.set()
                except:
                    pass

        elif self.requestSent == self.TEARDOWN:
            self.state = self.INIT
            self.teardownAcked = 1

    def openRtpPort(self):
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        try:
            self.rtpSocket.bind(("", self.rtpPort))
        except:
            tkinter.messagebox.showwarning(
                "Unable to Bind",
                f"Unable to bind PORT={self.rtpPort}"
            )

    def handler(self):
        self.pauseMovie()
        if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:
            self.playMovie()
