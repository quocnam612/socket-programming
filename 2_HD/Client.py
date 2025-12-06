from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os, time

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"
SOI = b'\xff\xd8'
EOI = b'\xff\xd9'

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
		self.master = master # store the master window (tkinter.Tk)
		self.master.protocol("WM_DELETE_WINDOW", self.handler) # call self.handler when the user closes the window instead of killing the program
		self.createWidgets() # build the GUI
		self.serverAddr = serveraddr # IP address of the server
		self.serverPort = int(serverport) # port number of the server
		self.rtpPort = int(rtpport) # port number for RTP packets
		self.fileName = filename # name of the video file
		self.rtspSeq = 0 # Initial RTSP sequence number
		self.sessionId = 0 # Initial RTSP session ID
		self.requestSent = -1 # Last request sent to the server (0 : SETUP, 1 : PLAY, 2 : PAUSE, 3 : TEARDOWN)
		self.teardownAcked = 0 # Flag to indicate if teardown is acknowledged
		self.connectToServer()
		self.frameNbr = -1

		self.lastFrame = None # last frame received from the server
		self.frameBuffer = bytearray() # buffer to hold the received segments until a full frame is assembled
		self.frameLoss = 0 # total lost frames
		self.packetCount = 0 # total received packets
		self.frameCount = 0 # total received frames
		self.bytesReceived = 0 # total received bytes
		self.startTime = None # time when the video starts playing
		self.frameTimes = [] # timestamps of received frames for FPS calculation
		
	def createWidgets(self):
		"""Build GUI."""
		# Make first row and 4 column expandable
		self.master.grid_rowconfigure(0, weight=1)
		for col in range(4):
			self.master.grid_columnconfigure(col, weight=1)
		
		# Video display frame
		self.videoFrame = Frame(self.master, bg="black")
		self.videoFrame.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5)
		self.videoFrame.bind("<Configure>", self.onWindowResize)
		self.label = Label(self.videoFrame, bg="black")
		self.label.pack(fill=BOTH, expand=True)
		self.displayWidth = self.videoFrame.winfo_width() or 640
		self.displayHeight = self.videoFrame.winfo_height() or 360

		# Control button frame
		buttonFrame = Frame(self.master)
		buttonFrame.grid(row=1, column=0, columnspan=4, sticky=E+W, padx=2, pady=2)
		for col in range(4):
			buttonFrame.grid_columnconfigure(col, weight=1)

		self.setup = Button(buttonFrame, text="Setup", command=self.setupMovie)
		self.setup.grid(row=0, column=0, padx=5, pady=2, sticky=E+W)
		self.start = Button(buttonFrame, text="Play", command=self.playMovie)
		self.start.grid(row=0, column=1, padx=5, pady=2, sticky=E+W)
		self.pause = Button(buttonFrame, text="Pause", command=self.pauseMovie)
		self.pause.grid(row=0, column=2, padx=5, pady=2, sticky=E+W)
		self.teardown = Button(buttonFrame, text="Teardown", command=self.exitClient)
		self.teardown.grid(row=0, column=3, padx=5, pady=2, sticky=E+W)

		# Stats label
		self.statsVar = StringVar()
		self.statsVar.set("Frame: 0 | Packets: 0 | Loss: 0 | FPS: 0.0 | Net: 0 kbps")
		self.statsLabel = Label(self.master, textvariable=self.statsVar, anchor=W)
		self.statsLabel.grid(row=2, column=0, columnspan=4, sticky=E+W, padx=5, pady=(0,5))
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)		
		self.master.destroy() # Close the gui window
		os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			# Create a new thread to listen for RTP packets
			threading.Thread(target=self.listenRtp).start() # create a thread to run listenRtp function simultaneously
			self.playEvent = threading.Event() # stopping signal for the thread
			self.playEvent.clear() # clear() function resets the internal flag to false which means the thread will run (set() would stop the thread meaning the internal flag is true -> pause)
			if self.startTime is None: # first time play
				self.startTime = time.time()
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				data = self.rtpSocket.recv(20480) # 20KB (20480 bytes) is the maximum size of an RTP packet
				if data:
					self.packetCount += 1
					self.bytesReceived += len(data)
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					frameId = rtpPacket.timestamp()
					print("Current Frame Num: " + str(frameId))

					if frameId < self.frameNbr:
						continue
					if frameId > self.frameNbr:
						if self.frameNbr >= 0 and frameId - self.frameNbr > 1:
							self.frameLoss += frameId - self.frameNbr - 1
						self.frameNbr = frameId
						self.frameBuffer.clear()
					self.frameBuffer.extend(rtpPacket.getPayload()) # append the payload to the frame buffer
					self.tryAssembleFrame()
			except:
				# Stop listening upon requesting PAUSE or TEARDOWN
				if self.playEvent.isSet(): # if the internal flag is true,  meaning pause
					break
				
				# Upon receiving ACK for TEARDOWN request,
				# close the RTP socket
				if self.teardownAcked == 1:
					try:
						# UDP sockets are connectionless; shutdown may raise when not connected,
						# so only close and swallow shutdown errors gracefully.
						self.rtpSocket.shutdown(socket.SHUT_RDWR) # best effort
					except OSError:
						pass
					self.rtpSocket.close() # Release the port (RTP and UDP port)
					break
					
	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT # e.g. cache-12345.jpg
		file = open(cachename, "wb") # open the file in binary write mode
		file.write(data) # write the received data to the file
		file.close()
		
		return cachename # return the file name (e.g. cache-12345.jpg)
	
	def updateMovie(self, imageFile):
		"""Update the image file as video frame in the GUI."""
		img = Image.open(imageFile)
		self.lastFrame = img.copy()
		self.frameTimes.append(time.time())
		self.renderFrame()
		self.updateStats()

	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # create a TCP socket (rtspSocket) attribute to connect to the server for RTSP (AF_INET: IPV4, SOCK_STREAM: TCP)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort)) # connect to the server using server address and server port
		except:
			# tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
			tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr) # tkMessageBox (Python 2) is changed to tkinter.messagebox (Python 3)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server."""	
		#-------------
		# TO COMPLETE
		#-------------
		
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
			request = "SETUP " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nTransport: RTP/UDP; client_port= " + str(self.rtpPort)
			

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
			request = "PLAY " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)

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
			request = "PAUSE " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)

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
			request = "TEARDOWN " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)
			
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
			reply = self.rtspSocket.recv(1024) # 1Kb (1024 bytes) is more than enough to receive the RTSP reply
			
			if reply: 
				self.parseRtspReply(reply.decode("utf-8")) # Decode the reply from bytes to string
			
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
		lines = data.split('\n')
		seqNum = int(lines[1].split(' ')[1]) # 1 (from the example)
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			session = int(lines[2].split(' ')[1])
			# New RTSP session ID
			if self.sessionId == 0:
				self.sessionId = session
			
			# Process only if the session ID is the same
			if self.sessionId == session:
				if int(lines[0].split(' ')[1]) == 200: # 200 (from the example)
					if self.requestSent == self.SETUP:
						#-------------
						# TO COMPLETE
						#-------------
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
						self.playEvent.set() # stop the thread (set() makes the internal flag true, clear() makes it false which means the thread will run)
					elif self.requestSent == self.TEARDOWN:
						# self.state = ...
						self.state = self.INIT

						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		#-------------
		# TO COMPLETE
		#-------------
		# Create a new datagram socket to receive RTP packets from the server
		# self.rtpSocket = ...
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # socket(IPV4, UDP), UDP for RTP

		# Set the timeout value of the socket to 0.5sec
		# ...
		self.rtpSocket.settimeout(0.5) # receive function will wait for 0.5 sec to receive data before throwing a timeout exception (this allows the listenRtp function to check periodically if the playEvent is set to stop the thread)

		try:
			# Bind the socket to the address using the RTP port given by the client user
			# ...
			self.rtpSocket.bind(('', self.rtpPort)) # '' means any address (INADDR_ANY)
		except:
			tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()

	def renderFrame(self):
		"""Render the cached frame scaled to fit the current window."""
		if self.lastFrame is None:
			return
		frame_w = self.videoFrame.winfo_width() or self.displayWidth
		frame_h = self.videoFrame.winfo_height() or self.displayHeight
		scale = min(frame_w / self.lastFrame.width, frame_h / self.lastFrame.height)
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

	def onWindowResize(self):
		self.displayWidth = max(1, self.videoFrame.winfo_width())
		self.displayHeight = max(1, self.videoFrame.winfo_height())
		self.renderFrame()

	def tryAssembleFrame(self):
		"""Reassemble JPEG frame using SOI/EOI markers inside buffered payload."""
		while True:
			start = self.frameBuffer.find(SOI)
			if start == -1:
				# nothing looks like frame start; drop garbage
				self.frameBuffer.clear()
				break
			end = self.frameBuffer.find(EOI, start + 2)
			if end == -1:
				# wait for the rest of the frame
				if start > 0:
					del self.frameBuffer[:start]
				break
			frame = self.frameBuffer[start:end + 2]
			del self.frameBuffer[:end + 2]
			self.updateMovie(self.writeFrame(frame))
		
	def updateStats(self):
		if self.startTime is None:
			return
		now = time.time()
		while self.frameTimes and now - self.frameTimes[0] > 1.0:
			self.frameTimes.pop(0) # keep only timestamps within the last second
		elapsed = max(0.001, now - self.startTime) 
		fps = len(self.frameTimes)
		throughput = (self.bytesReceived * 8 / 1000) / elapsed
		self.statsVar.set(
			f"Frame: {self.frameNbr} | Packets: {self.packetCount} | Loss: {self.frameLoss} | FPS: {fps:.1f} | Net: {throughput:.1f} kbps"
		)
